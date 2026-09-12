"use strict";

const fs = require("fs");
const vm = require("vm");

const appPath = process.argv[2];
if (!appPath) {
  throw new Error("app.js path is required.");
}

const source = fs.readFileSync(appPath, "utf8");
const start = source.indexOf("const nexussConversationStorageKey");
const end = source.indexOf(
  "async function restorePersistentConversation()",
  start,
);

if (start < 0 || end < 0) {
  throw new Error("Conversation initialization source was not found.");
}

const fragment = source.slice(start, end) + `
globalThis.__ensurePersistentConversation = ensurePersistentConversation;
globalThis.__startNewPersistentConversation =
  startNewPersistentConversation;
`;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function createHarness(outcomes = [true]) {
  const storage = new Map();
  let fetchCount = 0;
  let uuidCount = 0;
  let outcomeIndex = 0;

  const context = {
    console,
    Promise,
    setTimeout,
    clearTimeout,
    sessionId: "session-1",
    localStorage: {
      getItem(key) {
        return storage.has(key) ? storage.get(key) : null;
      },
      setItem(key, value) {
        storage.set(key, String(value));
      },
    },
    crypto: {
      randomUUID() {
        uuidCount += 1;
        return `00000000-0000-4000-8000-${String(uuidCount).padStart(12, "0")}`;
      },
    },
    apiHeaders() {
      return {
        "Content-Type": "application/json",
        "X-Nexuss-Session-ID": "session-1",
        "X-Nexuss-Session-Authenticated": "true",
      };
    },
    addMessage() {},
    async fetch(url, options) {
      fetchCount += 1;
      assert(url === "/v1/conversations", "Unexpected URL.");
      assert(options.method === "POST", "Expected POST.");
      await new Promise((resolve) => setTimeout(resolve, 8));

      const outcome = outcomes[
        Math.min(outcomeIndex, outcomes.length - 1)
      ];
      outcomeIndex += 1;

      if (!outcome) {
        return {
          ok: false,
          status: 503,
          async json() {
            return {
              detail: {
                message: "Temporary initialization failure.",
              },
            };
          },
        };
      }

      const body = JSON.parse(options.body);
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            conversation: {
              conversation_id: body.conversation_id,
              title: body.title,
            },
            messages: [],
          };
        },
      };
    },
  };

  vm.createContext(context);
  vm.runInContext(fragment, context);

  return {
    context,
    fetchCount: () => fetchCount,
  };
}

async function main() {
  const first = createHarness([true]);

  await Promise.all(
    Array.from(
      { length: 24 },
      () => first.context.__ensurePersistentConversation(),
    ),
  );
  assert(
    first.fetchCount() === 1,
    `Expected one concurrent initialization, got ${first.fetchCount()}.`,
  );

  await first.context.__ensurePersistentConversation();
  assert(
    first.fetchCount() === 1,
    "Successful initialization should remain cached.",
  );

  first.context.__startNewPersistentConversation();
  await Promise.all(
    Array.from(
      { length: 12 },
      () => first.context.__ensurePersistentConversation(),
    ),
  );
  assert(
    first.fetchCount() === 2,
    "A new conversation must create exactly one new initialization.",
  );

  const retry = createHarness([false, true]);
  let rejected = false;
  try {
    await retry.context.__ensurePersistentConversation();
  } catch (error) {
    rejected = /Temporary initialization failure/.test(
      String(error.message || error),
    );
  }
  assert(rejected, "The first failed initialization was not surfaced.");

  await retry.context.__ensurePersistentConversation();
  assert(
    retry.fetchCount() === 2,
    "A failed initialization must be retryable exactly once.",
  );

  console.log(
    "PASS: browser conversation initialization is single-flight, "
    + "cached after success, reset for a new conversation, and retryable "
    + "after failure.",
  );
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
