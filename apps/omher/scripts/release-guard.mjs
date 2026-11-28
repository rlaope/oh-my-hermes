#!/usr/bin/env node
// The release workflow's guard for omher's in-app update pointer (`omher-latest/latest.json`, BOUNDARY rule 20).
// Every omher on every computer reads that one file, so a bad write moves all of them at once. The guard refuses the
// three ways that has gone wrong or could:
//
//   verify   before anything is published: latest.json has the shape the updater reads, every payload it names is in
//            the release folder, and every signature verifies against the public key pinned in tauri.conf.json, the
//            way tauri-plugin-updater checks it on the person's computer (below). A signing-key mismatch used to pass
//            the old "the .sig is not empty" check and publish a manifest every client rejects.
//   precheck before the pointer is rewritten: the version now served must be lower than the new one (semver, pre-release
//            aware), so re-running an old tag or an older run finishing last never moves every client backwards. No
//            file yet (404) is a first publish and passes. OMHER_RELEASE_REPUBLISH=1 allows the same version again,
//            never a lower one; the workflow sets it only from its `republish` dispatch input, off by default.
//   confirm  after the upload: reads the public file back until it is the manifest just uploaded, and fails when it
//            never is, so a write that did not land does not read as a release.
//
// Node built-ins only (crypto has Ed25519 and BLAKE2b-512; fetch is global from Node 18), so the release job needs no
// package install for it. The pure parts are exported for release-guard.test.mjs, which `pnpm test` runs.
//
// How the updater verifies (tauri-plugin-updater 2.x `verify_signature`, minisign-verify 0.3): the pinned key and the
// manifest's signature are each base64 of a minisign text file. The key's second line is base64 of 42 bytes: the
// algorithm `Ed`, an 8-byte key id, the 32-byte Ed25519 key. The signature file's lines are an untrusted comment,
// base64 of 74 bytes (algorithm `ED` prehashed or `Ed` legacy, the key id, a 64-byte signature), `trusted comment: ...`
// and base64 of a 64-byte global signature. The key ids must match; the signature covers BLAKE2b-512 of the payload
// (prehashed) or the payload itself (legacy, which the updater allows); the global signature covers the signature
// followed by the trusted comment's text. Only after both verify is the trusted comment trusted: the Tauri CLI writes
// `version:<v>` there, and the updater refuses a manifest whose version is not the signed one when it requires that.
// `tauri build` always signs with the version, so the guard requires it and requires it to equal the manifest's.

import { createHash, createPublicKey, verify as edVerify } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

/** The updater targets latest.json carries, one per build in the release matrix. */
export const PLATFORMS = {
  "darwin-aarch64": "macos-arm64.app.tar.gz",
  "darwin-x86_64": "macos-x64.app.tar.gz",
  "windows-x86_64": "windows-x64-setup.exe",
  "linux-x86_64": "linux-x64.AppImage",
};

export class GuardError extends Error {}

// ---- semver (2.0.0, section 11: precedence; build metadata ignored) ----

const SEMVER =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

/** Parses a semver string; null when it is not one. */
export function parseSemver(text) {
  const m = typeof text === "string" ? SEMVER.exec(text) : null;
  if (!m) return null;
  return { core: [BigInt(m[1]), BigInt(m[2]), BigInt(m[3])], pre: m[4] ? m[4].split(".") : [] };
}

/** -1, 0 or 1 by semver precedence. Throws on a string that is not semver. */
export function compareSemver(a, b) {
  const x = parseSemver(a);
  const y = parseSemver(b);
  if (!x || !y) throw new GuardError(`not a semver version: ${!x ? JSON.stringify(a) : JSON.stringify(b)}`);
  for (let i = 0; i < 3; i++) if (x.core[i] !== y.core[i]) return x.core[i] < y.core[i] ? -1 : 1;
  // a version with a pre-release is lower than the same version without one
  if (!x.pre.length || !y.pre.length) return x.pre.length === y.pre.length ? 0 : x.pre.length ? -1 : 1;
  for (let i = 0; i < Math.min(x.pre.length, y.pre.length); i++) {
    const p = x.pre[i];
    const q = y.pre[i];
    if (p === q) continue;
    const pn = /^\d+$/.test(p);
    const qn = /^\d+$/.test(q);
    if (pn && qn) return BigInt(p) < BigInt(q) ? -1 : 1;
    if (pn !== qn) return pn ? -1 : 1; // numeric identifiers sort before alphanumeric ones
    return p < q ? -1 : 1; // ASCII order
  }
  return x.pre.length === y.pre.length ? 0 : x.pre.length < y.pre.length ? -1 : 1;
}

/**
 * Whether `next` may replace `published` as the pointer. `published` null is a first publish. `allowSame` (the
 * documented re-publish switch) lets the same version through again, never a lower one.
 */
export function decidePublish(next, published, allowSame = false) {
  if (published === null) return { ok: true, message: `no latest.json is published yet: first publish of ${next}` };
  const order = compareSemver(next, published);
  if (order > 0) return { ok: true, message: `${next} is newer than the published ${published}` };
  if (order === 0 && allowSame) {
    return { ok: true, message: `re-publishing ${next} over the same version (OMHER_RELEASE_REPUBLISH is set)` };
  }
  const why =
    order === 0
      ? `${next} is already the published version; set the workflow's republish input to publish it again on purpose`
      : `${next} is older than the published ${published}; publishing it would move every omher back`;
  return { ok: false, message: `refusing to rewrite omher-latest/latest.json: ${why}` };
}

// ---- minisign, as tauri-plugin-updater reads it ----

const STRICT_B64 = /^[A-Za-z0-9+/]+={0,2}$/;

function b64(text, what) {
  const t = typeof text === "string" ? text.trim() : "";
  if (!t || t.length % 4 !== 0 || !STRICT_B64.test(t)) throw new GuardError(`${what} is not base64`);
  return Buffer.from(t, "base64");
}

/** The pinned updater key (base64 of minisign's `.pub` text) as its key id and raw Ed25519 key. */
export function decodePublicKey(wrapped) {
  const lines = b64(wrapped, "the updater public key").toString("utf8").split(/\r?\n/);
  if (lines.length < 2) throw new GuardError("the updater public key has no key line");
  const bin = b64(lines[1], "the updater public key's key line");
  if (bin.length !== 42) throw new GuardError("the updater public key's key line is not 42 bytes");
  const alg = bin.subarray(0, 2).toString("latin1");
  if (alg !== "Ed" && alg !== "ED") throw new GuardError("the updater public key is not an Ed25519 minisign key");
  return { keyId: bin.subarray(2, 10), key: bin.subarray(10, 42) };
}

/** A manifest signature (base64 of a minisign `.sig` file) in its parts. */
export function decodeSignature(wrapped) {
  const lines = b64(wrapped, "the signature").toString("utf8").split(/\r?\n/);
  if (lines.length < 4) throw new GuardError("the signature file has fewer than four lines");
  const bin = b64(lines[1], "the signature line");
  if (bin.length !== 74) throw new GuardError("the signature line is not 74 bytes");
  if (!lines[2].startsWith("trusted comment: ")) throw new GuardError("the signature has no trusted comment");
  const global = b64(lines[3], "the global signature");
  if (global.length !== 64) throw new GuardError("the global signature is not 64 bytes");
  const alg = bin.subarray(0, 2).toString("latin1");
  if (alg !== "ED" && alg !== "Ed") throw new GuardError(`unsupported signature algorithm ${JSON.stringify(alg)}`);
  return {
    prehashed: alg === "ED",
    keyId: bin.subarray(2, 10),
    signature: bin.subarray(10, 74),
    trustedComment: lines[2].slice("trusted comment: ".length),
    globalSignature: global,
  };
}

function ed25519(message, key, signature) {
  const pub = createPublicKey({ key: { kty: "OKP", crv: "Ed25519", x: Buffer.from(key).toString("base64url") }, format: "jwk" });
  return edVerify(null, message, pub, signature);
}

/**
 * Verifies `payload` (a Buffer) against `signature` with `publicKey`, both as latest.json and tauri.conf.json hold
 * them. Returns the version the signature was bound to (null when it carries none). Throws GuardError when it does not
 * verify, with the reason the updater would give.
 */
export function verifySignature(payload, signature, publicKey) {
  const key = decodePublicKey(publicKey);
  const sig = decodeSignature(signature);
  if (!key.keyId.equals(sig.keyId)) {
    throw new GuardError(
      `signed by key ${Buffer.from(sig.keyId).reverse().toString("hex").toUpperCase()}, but tauri.conf.json pins key ` +
        `${Buffer.from(key.keyId).reverse().toString("hex").toUpperCase()}: every omher would refuse this update`,
    );
  }
  const message = sig.prehashed ? createHash("blake2b512").update(payload).digest() : payload;
  if (!ed25519(message, key.key, sig.signature)) {
    throw new GuardError("the signature does not match the payload's bytes: every omher would refuse this update");
  }
  const global = Buffer.concat([sig.signature, Buffer.from(sig.trustedComment, "utf8")]);
  if (!ed25519(global, key.key, sig.globalSignature)) {
    throw new GuardError("the signature's trusted comment was changed after signing");
  }
  const field = sig.trustedComment.split("\t").find((f) => f.startsWith("version:"));
  return field === undefined ? null : field.slice("version:".length);
}

// ---- latest.json and tauri.conf.json ----

/** The updater's one endpoint and pinned key from tauri.conf.json, with the repository the endpoint is on. */
export function readUpdaterConfig(conf) {
  const updater = conf?.plugins?.updater;
  const endpoints = updater?.endpoints;
  if (!Array.isArray(endpoints) || endpoints.length !== 1 || typeof endpoints[0] !== "string") {
    throw new GuardError("tauri.conf.json must name exactly one updater endpoint");
  }
  const m = /^https:\/\/github\.com\/([A-Za-z0-9._-]+\/[A-Za-z0-9._-]+)\/releases\/download\/omher-latest\/latest\.json$/.exec(
    endpoints[0],
  );
  if (!m) throw new GuardError(`the updater endpoint is not an omher-latest/latest.json release asset: ${endpoints[0]}`);
  if (typeof updater.pubkey !== "string" || !updater.pubkey) throw new GuardError("tauri.conf.json pins no updater key");
  decodePublicKey(updater.pubkey);
  return { endpoint: endpoints[0], repo: m[1], pubkey: updater.pubkey, version: conf.version };
}

/**
 * Checks latest.json is what the release workflow writes and the updater reads: a semver `version`, `notes`, an RFC
 * 3339 `pub_date`, and exactly the four platforms, each a non-empty signature and the URL of its payload on the
 * `omher-v<version>` release of `repo`. Returns `{ platform: file name }`.
 */
export function checkManifest(manifest, repo) {
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) throw new GuardError("latest.json is not an object");
  const { version, notes, pub_date: pubDate, platforms } = manifest;
  if (!parseSemver(version)) throw new GuardError(`latest.json version is not semver: ${JSON.stringify(version)}`);
  if (typeof notes !== "string") throw new GuardError("latest.json has no notes");
  if (typeof pubDate !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(pubDate)) {
    throw new GuardError("latest.json pub_date is not an RFC 3339 time");
  }
  if (!platforms || typeof platforms !== "object" || Array.isArray(platforms)) throw new GuardError("latest.json has no platforms");
  const want = Object.keys(PLATFORMS).sort();
  const got = Object.keys(platforms).sort();
  if (want.join() !== got.join()) throw new GuardError(`latest.json platforms are ${got.join(", ")}; expected ${want.join(", ")}`);
  const base = `https://github.com/${repo}/releases/download/omher-v${version}/`;
  const files = {};
  for (const target of want) {
    const entry = platforms[target];
    const name = `omher-${version}-${PLATFORMS[target]}`;
    if (!entry || typeof entry.signature !== "string" || !entry.signature.trim()) {
      throw new GuardError(`latest.json ${target} has no signature`);
    }
    if (entry.url !== base + name) throw new GuardError(`latest.json ${target} url is ${entry.url}; expected ${base + name}`);
    files[target] = name;
  }
  return files;
}

// ---- the public file ----

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** The manifest served at `url` now, or null when there is none (404). Throws on anything else. */
export async function fetchPublished(url, fetchImpl = fetch) {
  const res = await fetchImpl(url, { redirect: "follow", cache: "no-store", headers: { "cache-control": "no-cache" } });
  if (res.status === 404) return null;
  if (!res.ok) throw new GuardError(`GET ${url} answered ${res.status}`);
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new GuardError(`GET ${url} is not JSON`);
  }
}

/** Same manifest by value (key order aside). */
export function sameManifest(a, b) {
  const norm = (v) =>
    Array.isArray(v) ? v.map(norm) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, norm(v[k])])) : v;
  return JSON.stringify(norm(a)) === JSON.stringify(norm(b));
}

/**
 * Reads `url` until it serves `expected`, at most `attempts` times `delayMs` apart. Resolves with the attempt it
 * matched on; throws GuardError naming what was served last.
 */
export async function confirmPublished(url, expected, { attempts = 30, delayMs = 10_000, fetchImpl = fetch, wait = sleep, log = () => {} } = {}) {
  let last = "nothing";
  for (let i = 1; i <= attempts; i++) {
    try {
      const got = await fetchPublished(url, fetchImpl);
      if (got && sameManifest(got, expected)) return i;
      last = got === null ? "404" : `version ${JSON.stringify(got.version)}${got.version === expected.version ? " with other contents" : ""}`;
    } catch (e) {
      if (!(e instanceof GuardError) && !(e instanceof TypeError)) throw e; // TypeError: fetch's network failure
      last = e.message;
    }
    log(`attempt ${i}/${attempts}: ${url} serves ${last}`);
    if (i < attempts) await wait(delayMs);
  }
  throw new GuardError(`${url} still serves ${last} after ${attempts} reads, not ${expected.version} as just uploaded`);
}

// ---- command line ----

function args(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith("--")) out[argv[i].slice(2)] = argv[++i];
    else out._.push(argv[i]);
  }
  return out;
}

function need(opts, name) {
  if (typeof opts[name] !== "string" || !opts[name]) throw new GuardError(`--${name} is required`);
  return opts[name];
}

const readJson = (file) => JSON.parse(readFileSync(file, "utf8"));

async function main(argv) {
  const opts = args(argv);
  const [command] = opts._;
  const config = readUpdaterConfig(readJson(need(opts, "config")));
  const manifest = readJson(need(opts, "manifest"));
  const repo = need(opts, "repo");
  if (config.repo !== repo) {
    throw new GuardError(`omher reads its updates from ${config.repo}, but this run publishes to ${repo}`);
  }
  checkManifest(manifest, repo);
  if (command === "verify") {
    if (manifest.version !== config.version) {
      throw new GuardError(`latest.json says ${manifest.version}, tauri.conf.json says ${config.version}`);
    }
    const dir = need(opts, "dir");
    for (const [target, name] of Object.entries(checkManifest(manifest, repo))) {
      let signed;
      try {
        signed = verifySignature(readFileSync(path.join(dir, name)), manifest.platforms[target].signature, config.pubkey);
      } catch (e) {
        throw e instanceof GuardError ? new GuardError(`${target} (${name}): ${e.message}`) : e;
      }
      if (signed !== manifest.version) {
        throw new GuardError(`${name} is signed for version ${signed ?? "(none)"}, latest.json announces ${manifest.version}`);
      }
      console.log(`${target}: ${name} verifies against the pinned key, signed for ${signed}`);
    }
  } else if (command === "precheck") {
    let published;
    for (let i = 1; ; i++) {
      try {
        published = await fetchPublished(config.endpoint);
        break;
      } catch (e) {
        if (i >= 3 || !(e instanceof GuardError || e instanceof TypeError)) throw e;
        console.log(`reading ${config.endpoint} failed (${e.message}), trying again`);
        await sleep(5_000);
      }
    }
    if (published !== null && !parseSemver(published?.version)) {
      throw new GuardError(`the published latest.json has no semver version (${JSON.stringify(published?.version)}); fix it by hand first`);
    }
    const decision = decidePublish(manifest.version, published?.version ?? null, process.env.OMHER_RELEASE_REPUBLISH === "1");
    if (!decision.ok) throw new GuardError(decision.message);
    console.log(decision.message);
  } else if (command === "confirm") {
    const attempts = Number(opts.attempts ?? 30);
    const delayMs = Number(opts.delay ?? 10) * 1000;
    const n = await confirmPublished(config.endpoint, manifest, { attempts, delayMs, log: console.log });
    console.log(`${config.endpoint} serves ${manifest.version} (read ${n} time${n === 1 ? "" : "s"})`);
  } else {
    throw new GuardError("usage: release-guard.mjs verify|precheck|confirm --config <tauri.conf.json> --manifest <latest.json> --repo <owner/repo> [--dir <folder>]");
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((e) => {
    console.error(`release guard: ${e instanceof GuardError ? e.message : e?.stack ?? e}`);
    process.exit(1);
  });
}
