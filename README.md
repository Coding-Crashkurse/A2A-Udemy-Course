# A2A Course Directory Overview
This repository is a step-by-step A2A Protocol course. Each folder focuses on one concept and includes runnable examples.

A2A Protocol (GitHub): https://github.com/a2a-protocol

## Directories

Folder numbers follow the course teaching order. Modules 07–10 together cover
"task updates" (the four ways to follow a long-running task).

### 01_Message
Basic message structure, roles, and content parts.

### 02_Transports_Discovery
Transports and AgentCard discovery via well-known endpoints.

### 03_Task_Lifecycle
Task creation, status updates, and lifecycle events.

### 04_Configuration
Client and server configuration patterns.

### 05_StructuredData
Structured output and typed payloads.

### 06_FileExchange
File and artifact exchange via tasks.

### 07_Polling
Polling flow for task updates.

### 08_Streaming
Streaming updates and incremental responses.

### 09_Resubscribe
Resubscribe to a running task after a dropped connection.

### 10_PushNotifications
Push notifications (webhooks) for task updates.

### 11_MultiTurn_Context
Multi-turn conversations and context handling.

### 12_ListTasks
Listing and filtering tasks.

### 13_CancelTasks
Task cancellation and cleanup.

### 14_ErrorHandling
The A2A error catalog and how each error maps onto every transport
(HTTP / JSON-RPC / gRPC). Minimal server + client that provoke and inspect errors.

### 15_Security_Auth
Authentication and authorization flows (Auth0).

### 16_Capstone_Orchestrator
Capstone orchestrator that routes to sub-agents.

### 17_Advanced_Versioning
Protocol versioning and compatibility.

### 18_Advanced_ExtendedCard
Extended AgentCard endpoints and auth.

### 19_Advanced_Extensions
Protocol extensions and custom metadata.
