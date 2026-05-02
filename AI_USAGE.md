# AI Usage

## 0G Storage Sidecar Deploy Fix

- Files assisted: `sidecar-0gstorage/package.json`, `sidecar-0gstorage/tsconfig.json`, `sidecar-0gstorage/src/index.ts`
- Tooling: Codex helped diagnose the TypeScript module resolution failure and update the sidecar to the current official 0G Storage TypeScript SDK package.
- Human ownership: The team reported the deployment error and should review the SDK package change, rebuild the sidecar image, and run the demo path before pushing.
