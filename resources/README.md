# Deployment resources

Two ways to run the reduction on a schedule. Both invoke the **same** entry point
with the same parameters — `pii-reduction-databricks run <dataset> --configs <path>` —
so neither is a second implementation (`AGENTS.md` rule 10).

> **Status: skeleton, never deployed.** Nothing here has been applied to a workspace.
> The bundle is syntactically checked by a default-tier test (it parses, and it
> contains no workspace-identifying value), which is a different and much weaker
> claim than "it works". Treat the first deploy as the validation, and record the
> result in `docs/14_IMPLEMENTATION_PLAN.md` §8 when it happens.

## Path A — Asset Bundle (needs the Databricks CLI)

```bash
databricks bundle validate -t dev
```

```bash
databricks bundle deploy -t dev --var="dataset=my_tickets"
```

```bash
databricks bundle run pii_reduction -t dev
```

`databricks.yml` declares the variables; nothing in either file names a workspace,
a host, a catalog, a cluster or a warehouse.

## Path B — no CLI

**`bundle deploy` *is* the CLI**, so where policy blocks it, path A is unavailable
in full. The job itself does not need the CLI — only the deploy step does. Two
options:

1. **Create the job in the workspace UI.** Workflows → Create job → task type
   *Python wheel*, package `pii_reduction`, entry point `pii-reduction-databricks`,
   parameters `["run", "<dataset>", "--configs", "<configs path>"]`, on serverless
   compute with the dependencies listed in `pii_reduction_job.yml`. Upload the wheel
   (`python -m build --wheel`) to a Unity Catalog volume and reference it there —
   **and the spaCy model wheels too**, or the job will miss every person's name
   without saying so (see the dependency comment in `pii_reduction_job.yml`).
2. **POST the job definition to the Jobs API** using the same token you use for
   everything else:

   ```bash
   curl -X POST "${DATABRICKS_HOST:?set it}/api/2.1/jobs/create" -H "Authorization: Bearer ${DATABRICKS_TOKEN:?set it}" -H "Content-Type: application/json" -d @"$HOME/job.json"
   ```

   The fields are the ones in `pii_reduction_job.yml`, with `${var.…}` replaced by
   your values. Two things about that file: keep the **token** out of it (it comes
   from the environment above, and `:?` makes an unset variable fail loudly instead
   of posting an empty bearer), and keep the **file itself** out of the repository —
   it will contain your host, catalog and schema. Writing it to `$HOME` rather than
   the working tree is the easy way; `.gitignore` covers `job.json` as a backstop.

Either way the job authenticates as itself once it runs — ambient credentials on
Databricks compute — so no token, profile or host belongs in the job definition.

## What is deliberately absent

- **No schedule.** A skeleton that arrives scheduled runs against real data before
  anyone has read it. Add one when you mean it; `pii_reduction_job.yml` shows where.
- **No notebook task.** Logic lives in importable modules (`AGENTS.md` rule 3), and a
  scheduled notebook is the usual way that ends.
- **No table names, and no catalog/schema variables.** The job names a *dataset
  config*; the config names the tables, the destination and the reduced-only
  projection. Per-environment destinations are different dataset configs, not
  deploy-time overrides — so "what does prod write to" is answered by reading a file
  under review, not by finding the deploy command someone ran.
- **No workspace host.** The CLI resolves the target from the profile or environment
  it is already authenticated with.
