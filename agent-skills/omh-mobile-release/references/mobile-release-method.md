# Mobile Release Method

Load this while planning a store release. OMH prepares; the operator or CI builds, signs, uploads and submits, and each step is `prepared` until the store console or crash reporting shows it. Store rules change: confirm limits and dates in the current App Store Connect and Play Console documentation before quoting them.

## 1. Per-platform gates

| Gate | iOS (App Store) | Android (Google Play) |
| --- | --- | --- |
| signing | distribution certificate and App Store provisioning profile, each with an expiry; an App Store Connect API key for CI | an upload key in a keystore; with Play App Signing, Google holds the app signing key and a lost upload key can be reset |
| privacy | `PrivacyInfo.xcprivacy`: declared data types, tracking domains, and a reason for every required-reason API; third-party SDKs on Apple's list ship their own manifest | the Data safety form in Play Console, covering what every bundled SDK collects and shares |
| beta | TestFlight: internal testers without review; external groups need Beta App Review for the first build of a version; builds expire | testing tracks: internal, closed, open; each promotes to the next or to production; a personal developer account created after 2023-11-13 needs a closed test with at least 12 testers opted in continuously for 14 days before it can apply for production access |
| rollout | phased release of automatic updates over seven days, pausable; a manual download still gets the new build | staged rollout by percentage, raised step by step, haltable |
| no rollback | a released build stays installed; ship a higher build number, optionally with an expedited review request | a released `versionCode` stays installed; ship a higher `versionCode`, even when it is the old code rebuilt |

Toolchain minimum, checked at upload: iOS builds use the Xcode and SDK version Apple currently requires (Xcode 26 and the OS 26 SDKs since 2026-04-28); Android builds target the API level Play currently requires and, for a new app, ship as an app bundle (required since August 2021, https://developer.android.com/guide/app-bundle). Read the current numbers from Apple's upcoming-requirements page (https://developer.apple.com/news/upcoming-requirements/) and Play's target API level page (https://developer.android.com/google/play/requirements/target-sdk), and record the date read.

## 2. Before submitting

1. Every signing asset: its expiry, where it is held, and who can use it. A secret never enters the plan.
2. The SDK list the build actually ships, compared against the privacy manifest and the Data safety form.
3. The version string and the build number (`CFBundleVersion`, `versionCode`), and the next one reserved for a hotfix.
4. The beta group or track, its testers, and the checks they must pass.
5. The Play account type and creation date: a personal account created after 2023-11-13 puts the 14-day closed test on the timeline ahead of production access.

## 3. Rollout halt thresholds

| Signal | Source | Halts the step when |
| --- | --- | --- |
| crash-free users or sessions | crash reporting or the store console | below a stated floor, or below the previous version |
| ANR rate (Android) | Play Console Android vitals | above a stated ceiling |
| store rating or review volume | the store console | a stated drop within the step |
| a business metric the release touches | analytics | a stated drop against the previous version |

Each step also states the minimum number of sessions observed before its threshold is read; below it the step holds, because a crash-free rate over a handful of sessions is noise.

## 4. Hotfix

1. Halt or pause the rollout, so no new users receive the bad build.
2. Contain it server-side first when a feature flag or kill switch exists.
3. Build the fix with the reserved higher build number, run the shortest beta that proves it, and submit; on iOS decide whether to request an expedited review.
4. Roll the fix out in stages behind the same halt thresholds.

## 5. If the review rejects the build

1. Record the guideline number and the reviewer's message verbatim.
2. Decide between fix and resubmit (a new build number) and reply or appeal (no change to the binary).
3. Put a demo account with working credentials, and the way to reach any gated feature, in the review notes.
4. Before resubmitting, check the usual causes against the shipped build: in-app account deletion, a reachable privacy policy URL, App Privacy answers that match the SDKs, and the toolchain minimum in section 1.
