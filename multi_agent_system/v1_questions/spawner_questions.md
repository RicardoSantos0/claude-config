# Spawning Agent — Domain Expert Questions

1. Should spawned agents be created as Python classes, prompt files, configuration files, or all three?
2. What verification tests must a spawned agent pass before it can be used?
3. Should the Spawner maintain templates for common agent types?
4. How should the Spawner handle a request to spawn an agent type that has been created before but retired?
5. Should spawned agents have an expiration date?
6. How should the Spawner determine the minimum set of tools a new agent needs?
7. Should the Spawner produce a "behavioral contract" that specifies what the agent must and must not do?
8. What happens to a spawned agent's state when the project that spawned it ends?
9. Should the Spawner be able to clone and modify an existing agent, or must it always start from scratch?
10. How should the Spawner handle requests for agents that require tool access the system doesn't currently support?