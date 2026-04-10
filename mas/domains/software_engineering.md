# Domain Context: Software Engineering

## Core Principles
- SOLID: Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion
- DRY (Don't Repeat Yourself): single source of truth for every piece of knowledge
- YAGNI (You Ain't Gonna Need It): implement only what is currently needed
- KISS (Keep It Simple, Stupid): simpler solutions are preferred over complex ones
- Fail fast: surface errors early rather than masking them

## Quality Standards
- Code review required for all changes to production systems
- Tests must exist before code is considered complete (or TDD)
- CI/CD pipeline validates every change before merge
- Observability: logging, metrics, and tracing on all critical paths
- Documentation: public APIs, architecture decisions (ADRs), runbooks

## Common Risks
- Premature optimization: optimizing before profiling confirms a bottleneck
- Technical debt accumulation: shortcuts that compound over time
- Single points of failure: no redundancy in critical components
- Security: OWASP Top 10 — injection, broken auth, XSS, IDOR, misconfig
- Dependency risk: outdated packages, abandoned libraries, supply chain attacks
- Data loss: insufficient backup/restore procedures, lack of idempotency

## Best Practices
- Architecture Decision Records (ADRs) for significant technical choices
- Twelve-Factor App methodology for cloud-native services
- Feature flags for gradual rollouts and safe rollbacks
- Database migrations must be backward-compatible for zero-downtime deployments
- Security reviews for any change that handles authentication, authorization, or PII
- Load testing before releasing to production for performance-critical paths

## Prior Art
- Design patterns (GoF): Factory, Strategy, Observer, Decorator, etc.
- Distributed systems patterns: Circuit Breaker, Saga, CQRS, Event Sourcing
- RESTful API design guidelines (Richardson Maturity Model)
- OAuth2/OIDC for authentication; least-privilege for authorization
