## AWS Mainframe Modernization AI Agent Toolkits

This repository is a collection of AI agent skills and plugins that help
teams plan and execute mainframe modernization projects on AWS.

The toolkits follow the open [Agent Skills](https://agentskills.io)
standard, so each one can be dropped into the skills folder of any
compatible AI tool without modification.

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

## Questions and support

If you have any questions, please ask them on
[AWS re:Post](https://repost.aws/en/questions/ask) and add the tag
**AWS Transform for Mainframe** so the right community and experts can
help.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

