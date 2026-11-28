// The release guard's pure parts (scripts/release-guard.mjs), run by `pnpm test` in every omher CI job so the guard
// cannot rot between releases. The signing fixtures in release-guard-fixtures/ are TEST ONLY: a throwaway key made with
// `tauri signer generate` for this test (its private half was not kept) and a few payload bytes, signed with
// `tauri signer sign --app-version 9.9.9`; the other-key signature is the same payload signed by a second throwaway key.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  GuardError,
  checkManifest,
  compareSemver,
  confirmPublished,
  decidePublish,
  decodePublicKey,
  decodeSignature,
  fetchPublished,
  pinnedKeyAt,
  precheck,
  readUpdaterConfig,
  samePayloads,
  verifySignature,
} from "./release-guard.mjs";

const fixture = (name) => readFileSync(new URL(`./release-guard-fixtures/${name}`, import.meta.url));
const KEY = fixture("test-only-key.pub").toString("utf8").trim();
const PAYLOAD = fixture("test-only-payload.bin");
const SIG = fixture("test-only-payload.bin.sig").toString("utf8").trim();
const OTHER_SIG = fixture("test-only-payload.bin.other-key.sig").toString("utf8").trim();

/** Re-wraps a signature after changing its decoded minisign text. */
function rewrap(sig, edit) {
  const lines = Buffer.from(sig, "base64").toString("utf8").split("\n");
  edit(lines);
  return Buffer.from(lines.join("\n"), "utf8").toString("base64");
}

describe("compareSemver", () => {
  it("orders core versions numerically, not as text", () => {
    expect(compareSemver("1.2.10", "1.2.9")).toBe(1);
    expect(compareSemver("1.10.0", "1.9.9")).toBe(1);
    expect(compareSemver("2.0.0", "10.0.0")).toBe(-1);
    expect(compareSemver("1.2.4", "1.2.4")).toBe(0);
  });

  it("follows semver 2.0.0 pre-release precedence", () => {
    const ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"];
    for (let i = 0; i + 1 < ordered.length; i++) {
      expect(compareSemver(ordered[i], ordered[i + 1])).toBe(-1);
      expect(compareSemver(ordered[i + 1], ordered[i])).toBe(1);
    }
    expect(compareSemver("1.0.0+build.5", "1.0.0+build.9")).toBe(0);
  });

  it("refuses what is not semver", () => {
    for (const bad of ["1.2", "v1.2.3", "01.2.3", "1.2.3-", "", undefined]) {
      expect(() => compareSemver(bad, "1.0.0")).toThrow(GuardError);
    }
  });
});

describe("decidePublish", () => {
  it("passes a first publish and a newer version", () => {
    expect(decidePublish("1.2.4", null).ok).toBe(true);
    expect(decidePublish("1.2.5", "1.2.4").ok).toBe(true);
    expect(decidePublish("1.3.0", "1.3.0-rc.2").ok).toBe(true);
  });

  it("refuses an older version, even with the re-publish switch", () => {
    for (const allow of [false, true]) {
      const d = decidePublish("1.2.3", "1.2.4", allow);
      expect(d.ok).toBe(false);
      expect(d.message).toContain("older than the published 1.2.4");
    }
    expect(decidePublish("1.3.0-rc.1", "1.3.0").ok).toBe(false);
  });

  it("refuses the same version unless the re-publish switch is on", () => {
    expect(decidePublish("1.2.4", "1.2.4").ok).toBe(false);
    expect(decidePublish("1.2.4", "1.2.4").message).toContain("republish input");
    expect(decidePublish("1.2.4", "1.2.4", true).ok).toBe(true);
  });

  it("passes the same version when the served manifest already has these payloads (a re-run)", () => {
    expect(decidePublish("1.2.4", "1.2.4", false, true).ok).toBe(true);
    expect(decidePublish("1.2.4", "1.2.4", false, true).message).toContain("a re-run changes nothing");
    // never a lower version, whatever it holds
    expect(decidePublish("1.2.3", "1.2.4", true, true).ok).toBe(false);
  });
});

describe("precheck", () => {
  const repo = "rlaope/oh-my-hermes";
  const manifest = (version, sig = SIG, pubDate = "2026-11-28T03:00:00Z") => ({
    version,
    notes: `omher ${version}`,
    pub_date: pubDate,
    platforms: Object.fromEntries(
      ["darwin-aarch64", "darwin-x86_64", "windows-x86_64", "linux-x86_64"].map((t) => [
        t,
        { signature: sig, url: `https://github.com/${repo}/releases/download/omher-v${version}/omher-${version}-${t}` },
      ]),
    ),
  });
  const files = (m) => Object.fromEntries(Object.keys(m.platforms).map((t) => [t, `payload-${t}`]));
  const payload = () => PAYLOAD;
  const asked = [];
  const keyAt = (key) => async (tag) => {
    asked.push(tag);
    return key;
  };

  it("passes when every payload verifies against the key the published version pins", async () => {
    asked.length = 0;
    const m = manifest("1.2.5");
    const lines = await precheck(m, files(m), manifest("1.2.4"), { keyAt: keyAt(KEY), payload });
    expect(asked).toEqual(["omher-v1.2.4"]);
    expect(lines[1]).toContain("verifies against the key pinned at omher-v1.2.4");
  });

  it("refuses a tag whose payloads an installed omher cannot verify (the key changed with the secret)", async () => {
    const m = manifest("1.2.5", OTHER_SIG);
    await expect(precheck(m, files(m), manifest("1.2.4"), { keyAt: keyAt(KEY), payload })).rejects.toThrow(
      /installed omher 1\.2\.4 verifies updates with the key pinned at omher-v1\.2\.4.*key_rotation input/,
    );
    // a payload changed after signing is refused the same way
    const n = manifest("1.2.5");
    await expect(precheck(n, files(n), manifest("1.2.4"), { keyAt: keyAt(KEY), payload: () => Buffer.from("other") })).rejects.toThrow(
      GuardError,
    );
  });

  it("lets a deliberate key rotation through only with its own switch, not the republish one", async () => {
    const m = manifest("1.2.5", OTHER_SIG);
    await expect(precheck(m, files(m), manifest("1.2.4"), { allowSame: true, keyAt: keyAt(KEY), payload })).rejects.toThrow(GuardError);
    const lines = await precheck(m, files(m), manifest("1.2.4"), { rotate: true, keyAt: keyAt(KEY), payload });
    expect(lines[1]).toContain("key rotation (OMHER_RELEASE_KEY_ROTATION is set)");
  });

  it("skips the key check on a first publish", async () => {
    const m = manifest("1.2.5", OTHER_SIG);
    const never = async () => {
      throw new Error("no published version to read a key from");
    };
    const lines = await precheck(m, files(m), null, { keyAt: never, payload });
    expect(lines).toEqual(["no latest.json is published yet: first publish of 1.2.5", "first publish: no installed omher pins a key yet"]);
  });

  it("passes a re-run that would publish what is already served, and refuses other contents of the same version", async () => {
    const m = manifest("1.2.5");
    // the pointer upload landed, the read-back did not: the job runs again with the same manifest
    expect((await precheck(m, files(m), manifest("1.2.5"), { keyAt: keyAt(KEY), payload }))[0]).toContain("a re-run changes nothing");
    // a rebuilt release of the same version writes a new pub_date only: still the same payloads
    expect(samePayloads(m, manifest("1.2.5", SIG, "2026-11-29T00:00:00Z"))).toBe(true);
    // other signatures under the same version need the republish switch
    const resigned = manifest("1.2.5", rewrap(SIG, (l) => (l[0] = "untrusted comment: re-signed")));
    expect(samePayloads(resigned, m)).toBe(false);
    await expect(precheck(resigned, files(resigned), m, { keyAt: keyAt(KEY), payload })).rejects.toThrow(/republish input/);
    expect((await precheck(resigned, files(resigned), m, { allowSame: true, keyAt: keyAt(KEY), payload }))[0]).toContain("re-publishing");
    // another URL is other contents too
    const moved = manifest("1.2.5");
    moved.platforms["linux-x86_64"].url += "?x";
    expect(samePayloads(moved, m)).toBe(false);
  });

  it("reads the pinned key at a tag with one fixed gh call", () => {
    const calls = [];
    const run = (cmd, argv) => {
      calls.push([cmd, ...argv]);
      return JSON.stringify({ plugins: { updater: { pubkey: KEY } } });
    };
    expect(pinnedKeyAt(repo, "omher-v1.2.4", run)).toBe(KEY);
    expect(calls).toEqual([
      ["gh", "api", "-H", "Accept: application/vnd.github.raw+json", `repos/${repo}/contents/apps/omher/src-tauri/tauri.conf.json?ref=omher-v1.2.4`],
    ]);
    expect(() => pinnedKeyAt(repo, "omher-v1.2.4", () => "{}")).toThrow(/pins no updater key/);
    expect(() => pinnedKeyAt(repo, "omher-v1.2.4", () => "<html>")).toThrow(/not JSON/);
  });
});

describe("verifySignature", () => {
  it("decodes the key and signature as minisign does", () => {
    expect(decodePublicKey(KEY).key).toHaveLength(32);
    const sig = decodeSignature(SIG);
    expect(sig.prehashed).toBe(true);
    expect(sig.trustedComment).toMatch(/\tversion:9\.9\.9$/);
  });

  it("passes a good signature and returns the version it was signed for", () => {
    expect(verifySignature(PAYLOAD, SIG, KEY)).toBe("9.9.9");
  });

  it("refuses a signature from another key, by key id", () => {
    expect(() => verifySignature(PAYLOAD, OTHER_SIG, KEY)).toThrow(/pins key/);
  });

  it("refuses another key's signature even when it claims the pinned key's id", () => {
    const keyLine = Buffer.from(Buffer.from(KEY, "base64").toString("utf8").split("\n")[1], "base64");
    const forged = rewrap(OTHER_SIG, (lines) => {
      const bin = Buffer.from(lines[1], "base64");
      keyLine.copy(bin, 2, 2, 10);
      lines[1] = bin.toString("base64");
    });
    expect(() => verifySignature(PAYLOAD, forged, KEY)).toThrow(/does not match the payload/);
  });

  it("refuses a modified payload", () => {
    const changed = Buffer.from(PAYLOAD);
    changed[0] ^= 1;
    expect(() => verifySignature(changed, SIG, KEY)).toThrow(/does not match the payload/);
    expect(() => verifySignature(Buffer.concat([PAYLOAD, Buffer.from("x")]), SIG, KEY)).toThrow(GuardError);
  });

  it("refuses a trusted comment changed after signing (a re-labelled version)", () => {
    const relabelled = rewrap(SIG, (lines) => {
      lines[2] = lines[2].replace("version:9.9.9", "version:9.9.10");
    });
    expect(() => verifySignature(PAYLOAD, relabelled, KEY)).toThrow(/trusted comment was changed/);
  });

  it("refuses an empty or malformed signature", () => {
    for (const bad of ["", "not base64!", Buffer.from("one line").toString("base64")]) {
      expect(() => verifySignature(PAYLOAD, bad, KEY)).toThrow(GuardError);
    }
  });

  it("decodes the key omher pins today", () => {
    const conf = JSON.parse(readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));
    const cfg = readUpdaterConfig(conf);
    expect(cfg.repo).toBe("rlaope/oh-my-hermes");
    expect(cfg.endpoint).toBe("https://github.com/rlaope/oh-my-hermes/releases/download/omher-latest/latest.json");
    // the pinned key is not the test key, so a fixture can never verify as an omher build
    expect(() => verifySignature(PAYLOAD, SIG, cfg.pubkey)).toThrow(/pins key 1F14E9D263164245/);
  });
});

describe("checkManifest", () => {
  const repo = "rlaope/oh-my-hermes";
  const good = () => ({
    version: "1.2.5",
    notes: "omher 1.2.5",
    pub_date: "2026-11-28T03:00:00Z",
    platforms: {
      "darwin-aarch64": { signature: SIG, url: `https://github.com/${repo}/releases/download/omher-v1.2.5/omher-1.2.5-macos-arm64.app.tar.gz` },
      "darwin-x86_64": { signature: SIG, url: `https://github.com/${repo}/releases/download/omher-v1.2.5/omher-1.2.5-macos-x64.app.tar.gz` },
      "windows-x86_64": { signature: SIG, url: `https://github.com/${repo}/releases/download/omher-v1.2.5/omher-1.2.5-windows-x64-setup.exe` },
      "linux-x86_64": { signature: SIG, url: `https://github.com/${repo}/releases/download/omher-v1.2.5/omher-1.2.5-linux-x64.AppImage` },
    },
  });

  it("accepts what the release workflow writes and names each payload", () => {
    expect(checkManifest(good(), repo)).toEqual({
      "darwin-aarch64": "omher-1.2.5-macos-arm64.app.tar.gz",
      "darwin-x86_64": "omher-1.2.5-macos-x64.app.tar.gz",
      "windows-x86_64": "omher-1.2.5-windows-x64-setup.exe",
      "linux-x86_64": "omher-1.2.5-linux-x64.AppImage",
    });
  });

  it("refuses a missing platform, an empty signature, a URL on another tag and a bad version", () => {
    const missing = good();
    delete missing.platforms["linux-x86_64"];
    expect(() => checkManifest(missing, repo)).toThrow(/platforms/);
    const empty = good();
    empty.platforms["windows-x86_64"].signature = " ";
    expect(() => checkManifest(empty, repo)).toThrow(/no signature/);
    const elsewhere = good();
    elsewhere.platforms["darwin-x86_64"].url = elsewhere.platforms["darwin-x86_64"].url.replace("omher-v1.2.5", "omher-v1.2.4");
    expect(() => checkManifest(elsewhere, repo)).toThrow(/expected/);
    expect(() => checkManifest({ ...good(), version: "1.2" }, repo)).toThrow(/semver/);
    expect(() => checkManifest({ ...good(), pub_date: "yesterday" }, repo)).toThrow(/pub_date/);
  });
});

describe("the public file", () => {
  const url = "https://example.invalid/latest.json";
  const answer = (status, body) => async () => ({ status, ok: status >= 200 && status < 300, text: async () => body });

  it("reads a 404 as no file yet and anything else that fails as an error", async () => {
    expect(await fetchPublished(url, answer(404, "Not Found"))).toBeNull();
    await expect(fetchPublished(url, answer(500, ""))).rejects.toThrow(/500/);
    await expect(fetchPublished(url, answer(200, "<html>"))).rejects.toThrow(/not JSON/);
    expect(await fetchPublished(url, answer(200, '{"version":"1.2.4"}'))).toEqual({ version: "1.2.4" });
  });

  it("reads back until the file just uploaded is served", async () => {
    const expected = { version: "1.2.5", platforms: { a: 1 } };
    const served = [null, { version: "1.2.4" }, { platforms: { a: 1 }, version: "1.2.5" }];
    let i = 0;
    const fetchImpl = async () => {
      const v = served[i++];
      return v === null ? { status: 404, ok: false, text: async () => "" } : { status: 200, ok: true, text: async () => JSON.stringify(v) };
    };
    const log = [];
    const n = await confirmPublished(url, expected, { attempts: 5, delayMs: 0, fetchImpl, wait: async () => {}, log: (l) => log.push(l) });
    expect(n).toBe(3);
    expect(log).toEqual([`attempt 1/5: ${url} serves 404`, `attempt 2/5: ${url} serves version "1.2.4"`]);
  });

  it("fails when the new file is never served", async () => {
    const fetchImpl = async () => ({ status: 200, ok: true, text: async () => '{"version":"1.2.4"}' });
    await expect(
      confirmPublished(url, { version: "1.2.5" }, { attempts: 3, delayMs: 0, fetchImpl, wait: async () => {} }),
    ).rejects.toThrow(/still serves version "1.2.4" after 3 reads, not 1.2.5/);
  });
});
