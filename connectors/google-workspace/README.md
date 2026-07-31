# Google Workspace Connector

P6.8A uses a Google OAuth client of type **Desktop app**, the authorization-code
flow with PKCE, a loopback IP callback, and Windows user-scoped DPAPI storage.

Active authority is read-only:

- Gmail messages: `gmail.readonly`
- Calendar inventory: `calendar.calendarlist.readonly`
- Calendar events: `calendar.events.readonly`
- Contacts: `contacts.readonly`

No Gmail send, Calendar write, or Contacts write scope is requested.
