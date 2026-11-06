# Control Audit Method

Load this while planning a control test. OMH prepares; the auditor or control owner pulls the population, the evidence and the results, and each item stays `prepared` until its evidence is observed. Where the firm's or regulator's methodology differs from this page, the methodology governs; say which one was used.

## 0. Design first

Walk one item from initiation to evidence and record whether the control would prevent or detect the stated risk. If it would not, stop with a design deficiency before testing operation.

## 1. Population first

1. Name the population the control operates over: the period, the source system, and the unit (a journal entry, an access review, a change ticket).
2. Test completeness before sampling: reconcile the population count or total to an independent source.
3. Record how the sample was selected (random, systematic, or haphazard) and the seed or the interval, so another tester can draw the same items.

## 2. Sample size by control frequency

A commonly used starting point for a control expected to operate without deviation:

| Control frequency | Typical sample size |
| --- | --- |
| annual | 1 |
| quarterly | 2 |
| monthly | 2 to 5 |
| weekly | 5 to 15 |
| daily | 20 to 40 |
| several times a day | 25 to 60 |

Raise the size for a higher reliance, a lower tolerable deviation rate, or a control with a history of exceptions. An automated control tested once, with its change management tested, is the usual exception to frequency sizing.

When the firm gives a confidence level and a tolerable deviation rate and expects no deviations, the attribute-sampling size is ln(1 - confidence) / ln(1 - tolerable rate), rounded up (95% and 5% gives 59; 90% and 10% gives 22). Otherwise the table is a rule of thumb; say so.

## 2b. Deviations

For a control sampled at 25 items or fewer, one unexplained deviation means the control did not operate effectively for that population unless the firm's methodology allows a stated extended sample; record which rule applied. For a larger statistical sample compare the deviation rate with the tolerable rate. Evaluate compensating controls only after the deviation is recorded as a deviation.

## 3. Evidence, strongest first

| Procedure | What it shows | Enough on its own |
| --- | --- | --- |
| re-performance | the tester redoes the control and gets the same result | yes, for that item |
| inspection | a signed, dated document or system log shows the control happened | usually |
| observation | the tester watched it happen once | only for that moment |
| inquiry | someone said it happens | never |

A report, query or spreadsheet used to perform the control is tested for completeness and accuracy (source, parameters, a re-run) before items from it count as evidence. The sample covers the whole period of reliance; a control remediated during the period is tested for a stated minimum operating period afterwards, and earlier failures stay in the record.

## 4. Severity from stated criteria

Grade each deficiency from three stated inputs; show all three beside the grade:

| Reasonable possibility of a misstatement | Magnitude against stated materiality | Effective compensating control | Grade |
| --- | --- | --- | --- |
| yes | material | no | material weakness |
| yes | below material, but merits the attention of those charged with governance | no | significant deficiency |
| yes | material or significant | yes, and tested | re-grade at the magnitude the compensating control leaves |
| yes | inconsequential (not material and not worth the attention of those charged with governance) | any | control deficiency |
| no, or remote | any | any | control deficiency |

A restatement, fraud by senior management, or ineffective oversight by the audit committee are indicators of a material weakness whatever the table says. With any input missing, withhold the grade and name the missing input.
