# Disk checking and erase stopping

The graphical interfaces claim a transition on the event-loop thread before
starting a worker. Workers change model state only; they never call Tk or GTK.
The render timer compares the model with the last rendered screen, including
transitions completed between timer callbacks.

| State | Owner and permitted behavior |
| --- | --- |
| Last chance | Owner, token, method, target, and countdown must pass before a start claim. |
| Checking disk | One start claim owns a frozen confirmation. Navigation, refresh, erase, cancel, export, reset, and shutdown are unavailable. Closing the window leaves it open while checking finishes. |
| Working | The runner owns the process and inherited wipe lock. Normal progress polling continues. Cancel or window close claims stopping. |
| Stopping erase | One worker checks for a pre-existing terminal result, requests termination, and waits for cleanup. Duplicate cancel and incompatible actions are ignored. The interface states that erasure may still be running. |
| Finished | Published only after a terminal runner result and confirmed runner cleanup. Evidence saving remains an independent dimension. |

Final discovery runs outside the wizard state lock. It revalidates boot
identification, exclusions, selected identity, eligibility, and the frozen
confirmation before invoking the runner. The runner retains its own lock,
process guard, pinned binary checks, inherited file lock, and immediate
pre-exec device checks. No other operation can replace the claimed selection.

Cancellation uses the existing eight-second terminate wait, then a two-second
kill wait. If termination or cleanup cannot be confirmed, the interface returns
to Working with a warning and preserves runner ownership. Repeated cancellation
cannot signal the same process concurrently. A late poll cannot finish a
Stopping session. An already completed engine result retains its actual outcome.
An uncertain file-descriptor close blocks further terminal publication rather
than retrying a descriptor number that could have been reused.

A graphical failure invalidates pending startup. If launch has already crossed
that boundary, its worker requests a system-origin stop after launch returns.
No worker calls a destroyed window. A process that outlives an interface crash
retains the inherited wipe lock; same-boot recovery never attaches or resumes it.

The synchronous console entry points use the same claims and safety ordering.
Deterministic tests use event barriers with fake discovery, runners, and
processes. Rendered Tk tests cover both supported window sizes; GTK tests check
busy announcements, stale actions, and event-loop service while work is blocked.
