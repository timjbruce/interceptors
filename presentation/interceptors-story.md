---
marp: true
size: 16:9
paginate: true
title: The Next Universe
description: Temporal interceptors, told as a story. Rufus meets six business requirements without touching business logic.
style: |
  /* Palette lifted from the demo app (web/static/style.css) so the deck and the
     live UI look like one system. */
  :root {
    --bg: #0b1020; --panel: #141b32; --ink: #e7ecff; --muted: #8a95c0;
    --accent: #6ce0ff; --accent-2: #b58bff; --ok: #3ad29f; --warn: #ffcf6b;
    --bad: #ff6b8b; --line: #263056;
  }
  section {
    background:
      radial-gradient(1100px 620px at 74% -12%, #1a2450 0%, var(--bg) 58%);
    color: var(--ink);
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 27px;
    line-height: 1.5;
    padding: 62px 76px;
  }
  section::after { color: var(--muted); font-size: 16px; }
  h1 { font-size: 52px; margin: 0 0 18px; letter-spacing: -0.5px; }
  h2 { font-size: 38px; margin: 0 0 20px; color: var(--ink); letter-spacing: -0.3px; }
  h2 + p, h2 + ul, h2 + table, h2 + ol { margin-top: 4px; }
  h3 {
    font-size: 17px; margin: 30px 0 8px; color: var(--accent);
    text-transform: uppercase; letter-spacing: 0.14em; font-weight: 700;
  }
  strong { color: var(--accent); font-weight: 700; }
  em { color: var(--warn); font-style: italic; }
  a { color: var(--accent); }
  ul, ol { margin: 8px 0; }
  li { margin: 10px 0; }
  li::marker { color: var(--accent-2); }
  blockquote {
    border-left: 4px solid var(--accent-2); margin: 24px 0; padding: 4px 0 4px 24px;
    color: #c9d2f5; font-size: 26px;
  }
  code { background: var(--panel); border-radius: 5px; padding: 0.08em 0.3em; font-size: 0.92em; }
  pre {
    background: #0d132a; border: 1px solid var(--line); border-radius: 14px;
    padding: 20px 24px; margin: 20px 0;
  }
  pre code { background: none; padding: 0; font-size: 19px; line-height: 1.55; }
  table { border-collapse: collapse; width: 100%; font-size: 22px; margin: 12px 0; }
  th {
    text-align: left; color: var(--muted); font-size: 15px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.1em; border-bottom: 1px solid var(--line);
    padding: 8px 14px;
  }
  td { border-bottom: 1px solid var(--line); padding: 11px 14px; }
  tbody tr:last-child td { border-bottom: none; }
  section.title h1 { font-size: 66px; margin-bottom: 8px; }
  section.title h2 { color: var(--accent); font-size: 34px; font-weight: 500; margin-bottom: 48px; }
  section.title { padding-top: 150px; }
  section.bleed { padding: 0; }
  section.bleed::after { color: rgba(138, 149, 192, 0.55); }
---

<!--
Render:  npx @marp-team/marp-cli@latest presentation/interceptors-story.md -o deck.html
Runbook: presentation/README.md
-->

<!-- _class: bleed -->

![bg contain](images/00-title.svg)

<!--
0 - 1:00 quick intro

Interceptors

2 call outs - Rick and Josh

Interceptors = keeping business glue code out of workflows

-->

---

<!-- _class: bleed -->

![bg contain](images/01-san-dimas-2691.svg)

<!--
1:00 - 1:30

Following Rufus, the most excellent architect of the 27th century.

-->

---

<!-- _class: bleed -->

![bg contain](images/02-v1-no-auth.svg)

<!--
1:30 - 2:00

Simple workflow, no one woke up, anyone could travel, world peace was achieved.

-->

---

<!-- _class: bleed -->

![bg contain](images/03-next-universe.svg)

<!--
2:00 - 4:00

Multiverse of Bill & Ted, needed improvements to the workflow to do deal with this

1/ Real auth, 2/ Only Bill for save the future, to simplify things, 3/ write outs for when trips were authorized, so we could find them later, 4/ full log correlation, so the dudes in IT could find bad trips, if they occurred, 5/ most heinous auditors needed better controls on the back end systems

oh, yeah, do it everywhere

-->

---

<!-- _class: bleed -->

![bg contain](images/04-auth-standard.svg)

<!--

4:00 - 6:30

Great id provider; signed JWTs that are traveler credentials you can trust and need to validate based on actual clocks; delegation grants that act as a permission slip for the worker to get a token on behalf of a traveler; access token that can be used from the worker to the backend systems that can record the worker acted on behalf of a travler.
-->

---

<!-- _class: bleed -->

![bg contain](images/05-two-ways-to-lose.svg)

<!--
6:30 - 7:30

Here's why the requirements were there - De Nomolos; losing Napoleon with an untracked trip (d...jerk); ziggy piggy expense report.

-->

---

<!-- _class: bleed -->

![bg contain](images/06-every-workflow.svg)

<!--

7:30 - 8:30

Helper functions were not it - too much risk, could forget them if something changed, modify a lot of code

Being the most excellent architect that he was, Rufus did some research using Temporal's AI developer assistant, asking the question "what is the most excellent way to handle heinous cross-cutting requirements that need to be handled for multiple activities and workflows?"

-->

---

<!-- _class: bleed -->

![bg contain](images/07-middleware.svg)

<!--
8:30 - 9:30 - 

Interceptors - Hooks for the Temporal SDK to run code before and after Temporal SDK calls

-->

---

<!-- _class: bleed -->

![bg contain](images/08-five-categories.svg)

<!--

9:30 - 11:30

Where interceptors can run - client & worker

What are the types of interceptors? list the 5

Calls going into the primitive = inbound; calls going out from = outbound
-->

---

<!-- _class: bleed -->

![bg contain](images/09-how-to-build.svg)

<!--
11:30 - 14:30

1/ Extend the correct class - where it runs; Python Client.Interceptor & Worker.Interceptor

2/ Build a class that extends the specific type of interceptor you want to create, e.g. WorkflowInboundInterceptor, and over-ride methods of the Temporal SDK call, using the same signature. Delegate control back using super() or you short-circuit the chain (e.g. processing doesn't happen). You can raise errors to stop the call, too.

3/ Return an instance or the class back to the SDK and the SDK will register it into the chain of calls that will be made. Workflow interceptors are the class, activity and client are instances.

Register them! List out the order they run in, too!

-->

---

<!-- _class: bleed -->

![bg contain](images/10-activity-headers.svg)

<!--
14:30 - 17:30

1/ Rufus wanted to not update signatures across his project but he needed the values like correlation id and the delegation grant

a/ workflow outbound interceptors read values and create activity headers
b/ activity inbound interceptors read the header and create context variables in python
c/ activities can use or ignore the variables

2/ Headers get written to history and he needed to set HeaderCodecBehavior in addition to using a codec server. 

-->

---

<!-- _class: bleed -->

![bg contain](images/11-terms-to-interceptors.svg)

<!--
17:30 - 19:00

Rufus built the interceptors to meet the non-functional requirements

1/ Real auth & Group check
2/ Write out the log when trips get approved (not the data of the approval)
3/ Search attributes and correlation ids for all logs
4/ using the delegation grant to get an access token for backend calls

Interceptors made it easier to use with other workflows, also added debug time.
-->

---

<!-- _class: bleed -->

![bg contain](images/demo1-client.svg)

<!--
Show a few windows - traveler + admin browser
worker logs
backend system logs - the system that the worker calls to for time travel; requires an access token
temporal console
JWT Decoder

1/ Let's start with Auth cases - this demo shows the reason and is only for the demo!

a/ Ted trying to take a "save the future" -> declined invalid group; no workflow
b/ Evil Bill trying to take a "save the future" -> declined invalid JWT; no workflow

-->

---

<!-- _class: bleed -->

![bg contain](images/demo2-workflow-opens.svg)

<!--

For a trip that starts:

1/ workflow startup - correlation id, validation of JWT (clock!) that uses an activity (note the interceptors this creates, but pass over them), upsert search attributes
2/ grant prop - writes the validated grant to memory

workflow outbound

1/ reads the validated grant -> header
2/ reads the correlation id -> header

actiivty inbound

1/ gets the correlation id
2/ logs the start of the activity
3/ gets the grant header
4/ exchanges grant for token

activity calls the backend using the token

5/ end of activity is logged

-->

---

<!-- _class: bleed -->

![bg contain](images/demo3-decision.svg)

<!--

1/ workflow audit - captures that the signal came in, can write to another system

workflow outbound - repeat of earlier

1/ reads the validated grant -> header
2/ reads the correlation id -> header

activity inbound - repeat of earlier

1/ gets the correlation id
2/ logs the start of the activity
3/ gets the grant header
4/ exchanges grant for token

activity calls the backend using the token

5/ end of activity is logged

-->

---

<!-- _class: bleed -->

![bg contain](images/demo4-additional-demos.svg)

<!--

If we have time...

-->

---

<!-- _class: bleed -->

![bg contain](images/13-other-systems.svg)

<!--

34:00 - 35:00

Rufus share other ideas for interceptors

-->

---

<!-- _class: bleed -->

![bg contain](images/15-questions.svg)

<!--
35:00 -  

Questions
-->
