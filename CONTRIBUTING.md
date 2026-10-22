# Contributing Guidelines

Thank you for your interest in contributing to our project. Whether it's a bug report, new feature, correction, or additional
documentation, we greatly value feedback and contributions from our community.

Please read through this document before submitting any issues or pull requests to ensure we have all the necessary
information to effectively respond to your bug report or contribution.


## Reporting Bugs/Feature Requests

We welcome you to use the GitHub issue tracker to report bugs or suggest features.

When filing an issue, please check existing open, or recently closed, issues to make sure somebody else hasn't already
reported the issue. Please try to include as much information as you can. Details like these are incredibly useful:

* A reproducible test case or series of steps
* The version of our code being used
* Any modifications you've made relevant to the bug
* Anything unusual about your environment or deployment


## Contributing via Pull Requests
Contributions via pull requests are much appreciated. Before sending us a pull request, please ensure that:

1. You are working against the latest source on the *main* branch.
2. You check existing open, and recently merged, pull requests to make sure someone else hasn't addressed the problem already.
3. You open an issue to discuss any significant work - we would hate for your time to be wasted.

To send us a pull request, please:

1. Fork the repository.
2. Modify the source; please focus on the specific change you are contributing. If you also reformat all the code, it will be hard for us to focus on your change.
3. Ensure local tests pass.
4. Commit to your fork using clear commit messages.
5. Send us a pull request, answering any default questions in the pull request interface.
6. Pay attention to any automated CI failures reported in the pull request, and stay involved in the conversation.

GitHub provides additional document on [forking a repository](https://help.github.com/articles/fork-a-repo/) and
[creating a pull request](https://help.github.com/articles/creating-a-pull-request/).


## Finding contributions to work on
Looking at the existing issues is a great way to find something to contribute on. As our projects, by default, use the default GitHub issue labels (enhancement/bug/duplicate/help wanted/invalid/question/wontfix), looking at any 'help wanted' issues is a great place to start.


## Adding a skill or plugin

Plugins live in `plugins/<plugin-name>/`, one per concrete task (e.g.
`atx-fix-bfd-code-issue`). Don't group them in phase folders;
note the phase in the root README table instead. Skills go in `plugins/<plugin-name>/skills/<skill-name>/SKILL.md`. Names are
lowercase kebab-case, and a skill's frontmatter `name` must match its
directory.

**New skill in an existing plugin**

1. Create `plugins/<plugin>/skills/<skill>/SKILL.md` with `name` and
   `description` frontmatter. Write the description so an agent can tell
   *when* to use the skill. Put helper scripts in `scripts/` and longer
   docs in `references/`.
2. Refer to scripts relative to the skill directory, not the repo root.
   The skill is installed to different paths per tool.
3. Never write run output or learnings into the skill folder. Write to the
   user's workspace (e.g. `output/`).
4. Add the skill to the plugin's `README.md` and bump `version` in all three
   plugin manifests and in `.claude-plugin/marketplace.json`.

**New plugin**

1. Copy `plugins/atx-fix-bfd-code-issue/` as a template (manifests
   and README) and rename it.
2. Add an entry to all three catalogs: `.claude-plugin/marketplace.json`,
   `.agents/plugins/marketplace.json`, and `.cursor-plugin/marketplace.json`.
3. Add the plugin to the table in the root `README.md`.

**Before opening a PR**

```bash
python3 tools/validate.py
```

CI runs the same check. Do not commit customer source code or debug
bundles. Keep test data in `plugins/<plugin>/test/`, which is gitignored.

You can test locally before pushing:

```bash
# Claude Code: point at your local clone
/plugin marketplace add ./path/to/clone
# Agent Skills tools (Kiro, Copilot, ...) — skills CLI pinned to a tested release
npx skills@1.7.4 add ./path/to/clone --list
```


## Code of Conduct
This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct).
For more information see the [Code of Conduct FAQ](https://aws.github.io/code-of-conduct-faq) or contact
opensource-codeofconduct@amazon.com with any additional questions or comments.


## Security issue notifications
If you discover a potential security issue in this project we ask that you notify AWS/Amazon Security via our [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public github issue.


## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. We will ask you to confirm the licensing of your contribution.
