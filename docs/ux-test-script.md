# Observer script: lab user test

For the person watching (you). One tester, one sitting, about 60-90 minutes plus waiting for processing. Print this or keep it open on another screen. Record findings in `docs/ux-findings.md` (template at the end).

## Rules for the observer
- **Stay silent.** The tester has not seen the app before and gets no tour. Every question they ask is a finding: write it down instead of answering.
- **Do not point** at the screen, name a button or say "try the sidebar".
- If they ask "what should I do?" say: **"What would you try if I weren't here?"**
- If they are quiet, ask: **"What are you thinking?"** or **"What do you expect to happen?"** Never ask leading questions ("did you see the Results tab?").
- **Nudge only when stuck for about 2 minutes** (or if they want to give up). Write down the nudge you gave and the time. Level 1: "What does the page say?" Level 2: "Is there anything on this page you haven't tried?" Level 3: tell them, and mark the task "needed help".
- Do not defend or explain the design during the test. Thank them for confusion; it is the point of the test.
- Time each task (start when they begin, stop when they say they are done or you give level 3).

## Before the test (you, 20 minutes, not with the tester)
1. Use the release you want tested (`git tag`: `v0.1` or later) and run `cd frontend && npm run build` once, then `~/progders/bin/mrforge serve` (http://127.0.0.1:8000). Run `mrforge doctor`: everything must pass.
2. Create a **fresh workspace folder** for the tester's own workspace, or let them create it (this is part of Task 1). Do not use a workspace with results from earlier runs.
3. Choose the data. Suggested: `mri-test-data/full-deneme/1` (one subject: a T1 and a resting BOLD run; the BOLD run asks for a task name, which is a natural decision point). **Do a full dry run yourself first** and note how long processing takes, so you know whether the tester can wait for it or whether you should pre-process a second subject for Task 5.
4. Close other heavy programs. A batch of subjects slows the computer; give the tester one subject.
5. Put the tester at the keyboard. Open the app at `http://127.0.0.1:8000` and leave it on the workspace list. Have a notebook or `docs/ux-findings.md` open. If you can, record the screen (with the tester's agreement).
6. Do not show the README, CLAUDE.md or this script to the tester.

## What you say at the start (read it, do not improvise)
"This is a tool our lab might use to process MRI scans. I am testing the tool, not you; nothing you do can be wrong. Please think out loud: say what you are looking at and what you expect. I will not be able to answer questions, because I want to see what you would do alone. If you get completely stuck I will tell you. There are scan files in the folder `<path>`. Your job: get this subject's scan processed, and then tell me what was done to it and whether anything looks wrong."

## Tasks
Give them **one at a time**, on paper or read aloud. Do not tell them the screen names.

| # | Task (what you say) | Expected route | Watch for |
|---|---|---|---|
| 1 | "Create a place to work for this study." | Workspaces page: create | Do they find Create? Do they know what a workspace is? Naming hesitations |
| 2 | "Load the scan files from the folder `<path>`." | Data > Import scans, folder picker, review table | Do they understand the series table? The confidence words? The question about the task name (what do they type?) Are they afraid the original files are changed? |
| 3 | "Process this subject completely, from the raw scan to standard space." | Dashboard or Process > Pipelines: full processing dialog, confirm | Do they find it without help? Do they read the confirmation dialog? Do they understand the choices (smoothing, field map, artifact rejection)? Do they leave defaults alone or worry about them? |
| 4 | "While it runs: how can you tell how far it is, and what is it doing?" | Progress window, activity bell, Jobs page | Do they trust the status? Do they know when it is finished? Do they ask what a word means ("registration", "MNI")? |
| 5 | *(only if artifact rejection was ticked)* "The program may need something from you. Find out and do it." | Banner "Waiting for you", component review, label, Save and continue | Do they find the banner? Do they understand signal / noise / uncertain? Do they feel safe deciding? Do they find Save and continue? |
| 6 | "Look at the result. Is the brain image correct? Show it to me." | Subject page > Open in viewer / report | Can they open the viewer, change the underlay, find an overlay? Do they understand what they see? |
| 7 | "Tell me what was done to this subject and whether anything looks wrong, as if you were writing it for a colleague." | Subject page > Results (report), quality checks, motion numbers | Can they read the report? Do they understand the warnings and the motion numbers? Do they find Save report as HTML? What would they need to know that is missing? |
| 8 | "Decide whether this subject should be used in the analysis, and record that." | Quality decision card: Accept / Review / Exclude with a reason | Do they find it? Do they understand that a reason is required and why? |
| 9 | "Something went wrong (observer: see below). What happened and what would you do?" | Failure screen: plain-language error, View log, Retry, Resume | Do they understand the message? Is the next action obvious? |

For **Task 9**, before the test prepare a failing step on a second subject without the tester seeing, for example import the folder `full-deneme/4` (its BOLD run is cut off and cannot be converted), or give a step an unreadable T1. If you do not want to prepare one, skip Task 9 and note that.

## After each task (30 seconds)
Ask: **"How sure were you that you did it right? (1 = guessing, 5 = certain)"** and **"What was the most confusing part?"** Write both down.

## At the end (5 minutes)
1. "What was the best part? The worst part?"
2. "What words did you not understand?"
3. "Would you use this instead of what you use now? What would stop you?"
4. "Is there anything you expected to find and did not?"

## Severity (to fill in after the session, not during)
- **Blocker:** could not finish the task, or needed level 3 help.
- **Major:** finished, but only after a long hesitation, a wrong turn or a level 1-2 nudge.
- **Minor:** noticed, commented, or hesitated briefly.
- **Idea:** a suggestion from the tester.

## Findings template (copy into `docs/ux-findings.md`, one block per tester)
```markdown
## Tester <A / B>, <date>, release <tag>, observer <name>
Experience with MRI tools: <none / FSL / ...>   Total time: <min>

| # | Task | Screen | What they did / said | What they expected | Severity | Help given |
|---|------|--------|----------------------|--------------------|----------|------------|
| 1 | 3    | Pipelines | Clicked Anatomical first, then went back | One button "process everything" | Major | none |

Confidence (1-5) per task: 1:_ 2:_ 3:_ 4:_ 5:_ 6:_ 7:_ 8:_ 9:_
Words they did not understand: ...
Quotes worth keeping: ...
```

## What happens with the findings
Bring `docs/ux-findings.md` back to Claude Code: it turns the list into a prioritised fix list for you to approve (4a), applies the approved fixes (4b) and finalises the design-system notes (4c). A second tester then repeats the same tasks with the fixed release; the stage is accepted when the second tester has fewer or no stumbles than the first.
