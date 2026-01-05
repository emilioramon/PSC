graph TB
    %% Actor
    User[Usuario / Cliente]

    %% System boundary
    subgraph FaaS["FaaS Platform"]
        Gateway[faas-gateway<br/>API Gateway]

        Storage[storage-api<br/>Storage Service]
        ExecutionAPI[execution-api<br/>Execution Control API]
        Worker[execution-worker<br/>Execution Worker]

        Postgres[(PostgreSQL)]
        MinIO[(MinIO)]
        Redis[(Redis)]
        Kafka[(Kafka)]
        Zookeeper[(Zookeeper)]
    end

    %% External
    User -->|HTTP :8080| Gateway

    %% Internal flows
    Gateway -->|REST| Storage
    Gateway -->|REST| ExecutionAPI

    Storage -->|JDBC| Postgres
    Storage -->|S3 API| MinIO

    ExecutionAPI -->|Produce events| Kafka
    ExecutionAPI -->|State / Cache| Redis
    ExecutionAPI -->|REST| Storage

    Worker -->|Consume events| Kafka
    Worker -->|State / Locks| Redis
    Worker -->|Fetch code| MinIO

    Kafka --> Zookeeper

