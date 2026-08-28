# Async vs sync — a plain-language primer

A note-to-self on when to write `async def` and when not, using this repo's own
code as the example. No jargon.

## The one idea: waiting

Some operations make your program **wait**: asking another server for data,
querying a database, calling an LLM, reading a big file. While it waits, the CPU
is doing nothing — just sitting there until the answer comes back.

- **Sync code:** when you hit a wait, the whole program freezes on that line
  until it finishes. One thing at a time.
- **Async code:** when you hit a wait, the program can say *"come back to this
  when the answer arrives — meanwhile, let me do other things."*

That is the entire point of async: **don't sit frozen while waiting on something
slow.**

## Cooking analogy

You put pasta on to boil — 10 minutes.

- **Sync you:** stand and stare at the pot for 10 minutes, *then* chop vegetables.
- **Async you:** start the pasta, and *while it boils*, chop vegetables. When the
  timer beeps, come back to the pasta.

`await` is the timer beep. It marks a waiting point: "go do other useful work, come
get me when this is ready."

## Why it matters for a web server

Your API serves several people at once. Say 3 requests arrive together, each
needing a slow call:

- **Sync:** request 1's slow call freezes the worker. Requests 2 and 3 wait in
  line behind it.
- **Async:** while request 1 is waiting, the worker handles 2 and 3. All three get
  served in roughly the time of one.

## The subtlety that trips everyone up

"So async is for code that waits, sync is for code that doesn't?" **No — that's
the wrong cut, and it's the mistake to avoid.**

Sync code *also* waits. The difference is what happens *during* the wait:

- **Sync/blocking call:** the program is **frozen** during the wait.
- **Async call (with `await`):** the program is **free** to do other things
  during the wait.

Both wait the same amount of time. The question is whether the program is stuck or
free while it happens.

So the real decision has **two** parts:

1. Do I *want* the program free to do other work during this wait?
2. Does the library I'm calling *offer* an async version so it can?

You only get async behavior if **both** are true. A slow call made with a
*blocking* library is still sync — it still freezes — even though it waits.

## How this maps to this repo

Look at the online path: `interpret` and `answer` on the `Orchestrator`.

**`answer` is `async`.** It calls the search service through the MCP client:

```python
results = await self.search_client.search(...)   # ← waiting point, and it's async
```

The MCP client library is **async-only** — the only way to call it is to `await`
it. Once you `await` something, the function holding it must be `async` too, and so
must its caller (the FastAPI route). Async spreads upward from the library.

**`interpret` is plain `def` (sync) — but not for the reason you'd guess.**
It calls the query rewriter, which calls an LLM:

```python
response = litellm.completion(...)   # ← this IS a network call to an LLM. It waits.
```

So `interpret` genuinely waits on something slow. It is **not** "quick local work."
It is sync because `litellm.completion(...)` is the **blocking** version of the
call. There's no `await` in the code path, so the function is sync — and it
*freezes* during the LLM call.

Could it be async? Yes — litellm also offers `acompletion(...)`, the async
version. If we wanted `interpret` free to serve other requests during its LLM wait,
we'd switch to that and make `interpret` async. Today it's sync mostly because the
pipeline was written with the simple blocking call first.

Why is that OK for now? FastAPI runs a **sync** route handler in a background
thread, so one frozen `interpret` ties up a thread but doesn't freeze the whole
server. That's fine at low traffic; under real concurrency you'd move it to the
async LLM call.

(The **resolver**, the other half of the pipeline, is a genuine in-memory dict
lookup — no network, no LLM. *That* part really is quick local work and correctly
stays sync.)

## Rule of thumb

Don't ask "does this wait?" — almost everything waits on *something*. Ask:

> **Is this call slow (network / DB / disk / LLM), AND do I want the program free
> to do other work while it waits?**

- **Yes to both** → use the library's async call and `await` it → the function
  becomes `async`. (You need a library that offers an async version.)
- **It's fast local work** (transforming data in memory, a dict lookup, math) →
  keep it sync. Making it async adds ceremony for zero gain.
- **It's slow but you used the blocking call** (like `interpret` today) → it's
  sync and it *freezes* during the wait. Sometimes fine (low traffic + FastAPI's
  threadpool); revisit when concurrency matters.

Async is not a quality upgrade you sprinkle on. Add it when a library forces it, or
when you specifically want to overlap slow waits. Otherwise sync is simpler and
correct.

## Bridging the two worlds (for later)

- In async code, must call something blocking? → `await asyncio.to_thread(fn, ...)`
  so it doesn't freeze the loop.
- In sync code, must call one async thing? → `asyncio.run(coro())` — but never
  inside an already-running event loop.
