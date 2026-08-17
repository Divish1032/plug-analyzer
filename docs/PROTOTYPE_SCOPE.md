# Prototype Scope

**Updated:** 16 August 2026

This is the working list of feature-scope decisions for the SME prototype. Record a feature here whenever it is deferred or intentionally excluded because it adds complexity without supporting the current evaluation. Do not reintroduce a deferred feature without changing its status and documenting the reason.

| Feature | Prototype status | Current decision | Reconsider when |
|---|---|---|---|
| Pre-contact baseline correction | Deferred; UI disabled | Do not ask SMEs to select, approve, register, or subtract a pre-contact stack in the current prototype. The existing analysis implementation and tests remain in the codebase but are not exposed in the workflow. | The SME protocol consistently supplies matched pre-contact stacks and needs validated before/after-contact quantitative correction. |
| Human or manual reference validation | Removed from app | Do not collect typed SME values, cohorts, spreadsheets, or uploaded 3D masks in the prototype. External validation can stay in the SME's own tools. | The pilot has a defined reference format and needs one validated import workflow. |
| Saved app-run comparison | Included | Compare only immutable runs created by Plug Analyzer in the current project. Show Run B minus Run A and clear compatibility warnings. | Keep for the prototype. |
| Processed-image View dropdown | Removed | Always show the raw image with detected-plug and uncertain-edge overlays. The processed arrays remain internal to the calculation. | A processed view proves useful in a specific review task and can be made visibly distinct. |
| Acquisition-context form | Removed from UI | Do not ask for many optional fields that are not needed for the app-run workflow. | A declared before/after protocol requires the stored context. |
| Separate Storage screen | Removed | Keep only project size, Show project folder, and safe cached-image removal on the Project page. | Users need a tested storage task that cannot be handled in the project folder. |

## Current prototype principle

Prefer the simplest workflow that produces the measurements required for the current SME evaluation. A feature should remain out of the prototype unless it has a specific SME use case, the required input data is available reliably, and its added review or configuration burden is justified.
