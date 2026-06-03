# Security Policy

## Supported Versions

The project is early. Security fixes target the latest `main` branch until
versioned releases are established.

## Reporting a Vulnerability

Open a private security advisory on GitHub when available, or contact the
maintainer privately before publishing details.

Please include:

- affected command or file
- reproduction steps
- expected impact
- whether credentials, local files, or Hermes config can be affected

## Security Boundaries

`omh` is a local installer. It should not silently patch Hermes internals,
overwrite unmanaged files, or execute network actions during normal install,
apply, list, doctor, snippet, or uninstall commands.

