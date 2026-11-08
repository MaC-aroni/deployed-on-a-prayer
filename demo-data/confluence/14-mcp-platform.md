---
id: platform-mcp
title: "Platform: MCP Tool Platform"
parent: handbook
owner: platform-engineering
labels: [platform, mcp, ai, standard]
---
## What MCP tools are

Teams publish capabilities that AI agents and other services use as **MCP tools** (Model
Context Protocol). An MCP tool belongs to the team that owns its data; other teams consume it.

## How an MCP tool is hosted

- On AWS Lambda, following "Platform: Lambda Service Standard".
- It speaks MCP's **Streamable HTTP** transport in its **stateless** form: each HTTP POST
  carries one JSON-RPC message and gets one JSON reply. Notifications get `202 Accepted`. GET
  returns `405`, since there's no server-sent event stream.
- It supports protocol versions `2025-06-18` and `2025-03-26`, and offers `initialize`,
  `ping`, `tools/list` and `tools/call`.
- Its function URL uses **AWS_IAM** auth. **No consumer can call it until the owning team
  grants that consumer's role access.**

## How access is granted

- Access is a resource-based permission on the MCP tool's function, kept in the **owning
  team's repository** under `terraform/access`, so the owner controls who may call it.
- Grant two permissions to the consumer's role ARN: `lambda:InvokeFunctionUrl` with
  `function_url_auth_type = "AWS_IAM"`, and `lambda:InvokeFunction`.
- Removing the access is `terraform destroy` on that component.
- Every grant needs approval first. See "Access: Requesting Access to an MCP Tool".

## How consumers call it

Consumers find the tool's URL with `lambda:GetFunctionUrlConfig`, call `initialize`, send
`notifications/initialized`, then call tools. Every request is signed with the consumer's role.
A `403` means the role hasn't been granted access.
