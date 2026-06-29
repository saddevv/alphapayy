# Operations Coverage

This standalone app keeps the Microsoft Graph operation model from the existing integrated Graph agent.

## Tool wrappers

`graph_agent/tools.py` includes **109** Graph tool wrappers (`@tool`).

## Registry-backed operation families

- `applications`: 5
- `attackSimulation`: 8
- `devices`: 3
- `ediscovery`: 6
- `groups`: 11
- `identitiesHealth`: 3
- `identitiesSensors`: 4
- `secureScore`: 2
- `security`: 6
- `threatIndicator`: 5
- `threatSubmission`: 3
- `users`: 13

Total unique registry operations: **69**

## Runtime verification

Use:

- `GET /graph/operations`
- `GET /graph/operations/{resource_type}`

to validate operations available in the running service.
