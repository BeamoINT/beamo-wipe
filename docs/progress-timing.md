# Operation progress and timing

The pinned nwipe source (`6082bde060091e66365d852a1877f2ee80c67105`,
`src/nwipe.c`, `signal_hand`) supplies job-wide `round_percent`, round/pass
counters, an engine ETA, and an explicit pass-type marker. These observations
are presentation data; the existing process-exit and completion-log checks
remain the only completion decision. No engine flags, signal cadence, device
checks, cancellation waits, or ownership locks change.

## Phases

Preparing means no engine percentage has been reported since launch. Writing
and Verifying require explicit target-bound engine markers. Blanking is a
write. Syncing and Retrying retain their names because either can happen
between passes. Missing/unknown markers say Phase not reported. An observation
more than ten seconds old is labelled last reported; polling an unchanged log
never makes it fresh. Stopping belongs to the cancellation owner, and Finalizing
means process exit was observed and terminal processing/cleanup is pending.
Neither phase means successful completion.

## Estimated time remaining

The estimate is omitted unless all of these hold:

- Six advancing samples span at least twenty seconds, with each interval
  between two and ten seconds. Buffered lines count as one observation, not
  invented historical timing samples.
- Every increase is at least twice the engine's reported percentage quantum;
  the window spans at least one percentage point and ten quantization units.
- The fastest interval rate is no more than 1.5 times the slowest, and the
  measured job-wide projection agrees with the engine ETA within a factor of
  1.5. The larger of those two estimates is displayed.
- This is the final round/pass and final operation: verification for the
  methods that request it, or writing for Quick zero. Earlier writing rates
  cannot predict the unmeasured read-back rate.

Phase/counter changes, regressions, missing data, timestamp discontinuities,
clock changes and gaps clear history. Local wall/monotonic disagreement over
100 milliseconds clears history; engine log timestamps have whole-second
resolution and use a two-second comparison tolerance. Duplicated percentages
cannot renew rate freshness. A regression must catch up to the prior high-water mark before a new
window can form. Unstable or inadequate rates suppress the estimate. There is
no estimate at 100%, during stopping/finalizing, after a result, or after
recovery. The interface never decrements an old ETA between engine samples.

The exact label is Estimated time remaining. Values use less than one minute,
rounded-up minutes, five-minute buckets, or whole hours, never seconds. This is
an estimate of remaining engine work; final cleanup or report-saving time is
unknown. Fast operations and slow quantized streams may never show an estimate.

## Shared presentation and evidence

Every interface uses the same progress view. Displayed integer percentages
update at most once per five seconds; phase changes and terminal results are
immediate. Existing percentage clamping is preserved: 100% is unavailable until
the existing completion check succeeds. Elapsed text changes at minute
boundaries. GTK does not emit redundant text changes, and plain console output
does not repeat unchanged status or device identity on every poll.

Elapsed time uses monotonic time from successful runner startup to the observed
terminal result, including preparation and stopping. The frozen endpoint also
feeds the evidence duration, so slow evidence writes and bounded save retries
cannot lengthen the operation. Wall-clock adjustments invalidate ETA history
but do not change elapsed time. An invalid/backward monotonic clock makes
elapsed unavailable and prevents a valid terminal timing record from being
claimed. Recovery displays only the saved duration, never resumes a timer or
restores an ETA. Live samples and estimates are not written to reports and
cannot become completion proof. Existing volatile evidence and privacy rules
remain unchanged: shutdown or power loss loses evidence unless exported.

Deterministic tests use controllable clocks and fake output for incomplete,
foreign, irregular, duplicated, regressing, multi-phase, fast, slow, stalled,
long-duration and clock-change streams. Rendered Tk/GTK tests cover readable
long-duration text, stable controls and duplicate accessibility events.
