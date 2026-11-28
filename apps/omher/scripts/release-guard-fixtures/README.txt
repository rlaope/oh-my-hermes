TEST ONLY. These files exist for apps/omher/scripts/release-guard.test.mjs and nothing else.

test-only-key.pub                     the public half of a throwaway key made with `tauri signer generate`
                                      for this test; its private half was never kept. It is NOT omher's
                                      updater key (that one is pinned in src-tauri/tauri.conf.json).
test-only-payload.bin                 a few bytes standing in for an updater bundle
test-only-payload.bin.sig             `tauri signer sign --app-version 9.9.9` of that payload with the key above
test-only-payload.bin.other-key.sig   the same payload signed by a second throwaway key

Never point a manifest, a release or the app at any of these.
