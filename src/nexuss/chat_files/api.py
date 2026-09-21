"""Authenticated chat-file upload and artifact download API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse

from nexuss.chat_files.models import (
    ArtifactRecord,
    AttachmentRecord,
    CreateTextArtifactRequest,
    PackageAttachmentsRequest,
)
from nexuss.chat_files.store import ChatFileError, WorkspaceFileStore
from nexuss.conversation.models import ConversationRoute
from nexuss.conversation.store import SQLiteConversationStore

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def register_chat_file_routes(
    app: FastAPI,
    *,
    require_local_control: Callable[[Request], None],
) -> WorkspaceFileStore:
    files = WorkspaceFileStore()
    conversations = SQLiteConversationStore()

    def validate_conversation(
        *,
        conversation_id: UUID,
        session_id: UUID,
        authenticated: bool,
    ) -> None:
        conversation = conversations.get(conversation_id)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation was not found.",
            )
        if (
            not authenticated
            or conversation.user_session_id != session_id
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Conversation session does not match.",
            )

    def translate(exc: ChatFileError) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        )

    @app.post(
        "/v1/conversations/{conversation_id}/attachments",
        response_model=AttachmentRecord,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_attachment(
        conversation_id: UUID,
        request: Request,
        file_name: Annotated[
            str,
            Header(alias="X-Nexuss-File-Name"),
        ],
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
        content_length: Annotated[
            int | None,
            Header(alias="Content-Length"),
        ] = None,
    ) -> AttachmentRecord:
        require_local_control(request)
        validate_conversation(
            conversation_id=conversation_id,
            session_id=session_id,
            authenticated=authenticated,
        )
        if (
            content_length is not None
            and content_length > _MAX_UPLOAD_BYTES
        ):
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Chat attachments are limited to 25 MB each.",
            )

        data = await request.body()
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Chat attachments are limited to 25 MB each.",
            )

        try:
            return files.save_attachment(
                conversation_id=conversation_id,
                user_session_id=session_id,
                name=unquote(file_name),
                media_type=(
                    request.headers.get("content-type")
                    or "application/octet-stream"
                ),
                data=data,
            )
        except ChatFileError as exc:
            raise translate(exc) from exc

    @app.get(
        "/v1/conversations/{conversation_id}/attachments",
        response_model=list[AttachmentRecord],
    )
    def list_attachments(
        conversation_id: UUID,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> list[AttachmentRecord]:
        require_local_control(request)
        validate_conversation(
            conversation_id=conversation_id,
            session_id=session_id,
            authenticated=authenticated,
        )
        return list(files.list_attachments(conversation_id))

    @app.post(
        "/v1/conversations/{conversation_id}/artifacts/package",
        response_model=ArtifactRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def package_attachments(
        conversation_id: UUID,
        body: PackageAttachmentsRequest,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> ArtifactRecord:
        require_local_control(request)
        validate_conversation(
            conversation_id=conversation_id,
            session_id=session_id,
            authenticated=authenticated,
        )
        try:
            artifact = files.create_package(
                conversation_id=conversation_id,
                user_session_id=session_id,
                attachment_ids=body.attachment_ids,
                name=body.name,
            )
            conversations.append_turn(
                conversation_id=conversation_id,
                user_text=(
                    body.instruction
                    or "Package the attached files."
                ),
                assistant_text=(
                    f"Packaged {len(body.attachment_ids)} attached "
                    f"file(s) into {artifact.name}."
                ),
                route=ConversationRoute.CHAT,
                provider_id="nexuss",
                model="local-artifact-packager",
                pending_action=None,
                pending_capability_hint=None,
                attachment_ids=body.attachment_ids,
            )
            return artifact
        except ChatFileError as exc:
            raise translate(exc) from exc

    @app.post(
        "/v1/conversations/{conversation_id}/artifacts/text",
        response_model=ArtifactRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def create_text_artifact(
        conversation_id: UUID,
        body: CreateTextArtifactRequest,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> ArtifactRecord:
        require_local_control(request)
        validate_conversation(
            conversation_id=conversation_id,
            session_id=session_id,
            authenticated=authenticated,
        )
        try:
            return files.create_text_artifact(
                conversation_id=conversation_id,
                user_session_id=session_id,
                name=body.name,
                content=body.content,
                media_type=body.media_type,
            )
        except ChatFileError as exc:
            raise translate(exc) from exc

    @app.get("/v1/artifacts/{artifact_id}/download")
    def download_artifact(
        artifact_id: UUID,
        request: Request,
        session_id: Annotated[
            UUID,
            Header(alias="X-Nexuss-Session-ID"),
        ],
        authenticated: Annotated[
            bool,
            Header(alias="X-Nexuss-Session-Authenticated"),
        ],
    ) -> FileResponse:
        require_local_control(request)
        resolved = files.get_artifact(artifact_id)
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact was not found.",
            )
        record, path = resolved
        if not authenticated or record.user_session_id != session_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Artifact session does not match.",
            )
        return FileResponse(
            path,
            media_type=record.media_type,
            filename=record.name,
        )

    return files
