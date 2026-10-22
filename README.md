## AWS Mainframe Modernization AI Agent Toolkits

This repository is a plugin marketplace of AI agent skills and plugins
that help teams plan and execute mainframe modernization projects on AWS.
It can be installed directly from Claude Code, Codex, and Cursor, and its
skills can be installed into Kiro and any other tool that supports the
open [Agent Skills](https://agentskills.io) standard.

---

### How this fits with reimagine of mainframe applications using AWS Transform

[AWS Transform for mainframe](https://aws.amazon.com/transform/mainframe/)
is an agentic AI service that reimagines mainframe applications into
AI-ready, cloud-native systems, compressing modernization timelines from
years to months. AWS Transform handles the heavy lifting of
understanding the legacy estate, extracting the business rules, and generating the requirements;
from there, teams use coding agents like Kiro, Claude Code, Codex, and others to design and build the target microservices, complete with production-ready code and infrastructure.

The reimagine approach follows a three-phase methodology:

1. **Reverse engineering** — AWS Transform for mainframe extracts business
   logic, data models, and dependencies from COBOL/JCL source and runtime
   metrics, producing traceable documentation and business rule
   specifications.
2. **Forward engineering** — AI agents/Kiro turn those extracted rules into
   microservice specifications, target database designs, and source code,
   with humans in the loop validating business logic and architecture at
   each step.
3. **Deploy and test** — the generated microservices and infrastructure as
   code are deployed to AWS and validated for functional equivalence with
   the original application.

Reusable samples of skills and plugins are provided here to help you accelerate your modernization journey.

## Plugins

Each plugin covers one concrete modernization task and bundles the skills
for it. The phase column only groups them for browsing. It is not part of
the install path.

| Plugin | Phase | Status |
|---|---|---|
| [atx-fix-bfd-code-issue](plugins/atx-fix-bfd-code-issue/) | Reverse engineering | Available |
| generate-doc-from-atx-requirements | Reverse engineering | Planned |
| atx-requirements-to-spec | Forward engineering | Planned |
| data-migration, data-validation-reconciliation | Data migration | Planned |
| functional-testing, performance-baseline-comparison | Validation and testing | Planned |
| observability-instrumentation | Production readiness | Planned |
| cutover-runbook-generation, rollback-strategy | Deployment and cutover | Planned |

## Install

### Claude Code

```
/plugin marketplace add aws-samples/sample-mainframe-modernization-agent-skills
/plugin install atx-fix-bfd-code-issue@mainframe-modernization
```

Update later with `/plugin marketplace update mainframe-modernization`.

### Codex

```bash
codex plugin marketplace add aws-samples/sample-mainframe-modernization-agent-skills
```

Then run `codex plugin add atx-fix-bfd-code-issue@mainframe-modernization`,
or launch Codex, run `/plugins`, choose the **Mainframe Modernization on
AWS** marketplace, and install the plugin you need.

### Cursor

**Settings → Plugins → Team Marketplaces → Add Marketplace → Import from
Repo**, pointing at `aws-samples/sample-mainframe-modernization-agent-skills`.
Then install the plugin from the **Plugins** panel.

### Kiro CLI

Kiro loads skills from `.kiro/skills/` (workspace) and `~/.kiro/skills/`
(global). Install with the [`skills`](https://github.com/vercel-labs/skills) CLI,
pinned to a specific tested release:

```bash
# workspace
npx skills@1.7.4 add aws-samples/sample-mainframe-modernization-agent-skills -a kiro-cli
# global
npx skills@1.7.4 add aws-samples/sample-mainframe-modernization-agent-skills -a kiro-cli -g
```

The default agent picks them up automatically. Custom agents need
`"skill://.kiro/skills/**/SKILL.md"` (or the `~/.kiro` equivalent) in
their `resources`.

### Other tools (GitHub Copilot, Devin, Gemini CLI, ...)

Pin the `skills` CLI to a specific tested release:

```bash
npx skills@1.7.4 add aws-samples/sample-mainframe-modernization-agent-skills          # pick skills/agents interactively
npx skills@1.7.4 add aws-samples/sample-mainframe-modernization-agent-skills --list   # list available skills
```

You can also copy a skill folder (e.g.
`plugins/atx-fix-bfd-code-issue/skills/fix-atx-datapath-errors/`)
into your tool's skills directory without renaming it.

## Repository layout

```
.claude-plugin/marketplace.json     Claude Code marketplace catalog
.agents/plugins/marketplace.json    Codex marketplace catalog
.cursor-plugin/marketplace.json     Cursor marketplace catalog
plugins/<plugin>/
  .claude-plugin/plugin.json        per-tool plugin manifests
  .codex-plugin/plugin.json
  .cursor-plugin/plugin.json
  skills/<skill>/SKILL.md           skills (shared by every tool)
  skills/<skill>/scripts/           helper scripts the skill runs
  skills/<skill>/references/        docs the skill reads on demand
  README.md
tools/validate.py                   catalog/manifest/skill validation (run in CI)
```

See [CONTRIBUTING](CONTRIBUTING.md#adding-a-skill-or-plugin) to add a skill
or plugin.

## Questions and support

If you have any questions, please ask them on
[AWS re:Post](https://repost.aws/en/questions/ask) and add the tag
**AWS Transform for Mainframe** so the right community and experts can
help.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
