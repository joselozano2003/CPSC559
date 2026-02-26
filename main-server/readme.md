## Prerequisites:

- Docker and Docker Compose installed on your machine.
- Python 3.10 or higher installed (for local development).

**Note for Apple Silicon (M1/M2/M3) Users:**

- The local `Dockerfile` works natively on ARM64 (Apple Silicon)

## Initialization Steps:

1. Ensure that all prerequisites are met
2. Copy the contents from `.env.example` and create a new file named `.env` in the root directory of this repository
3. Execute the command `make up` in the terminal in the root directory of this repository, to start up the server
4. When done, execute the command `make down` in the terminal in the root directory of this repository, to shut down the server


## S3 Image Storage

The application uses different storage solutions for local development and production:

### Local Development (MinIO) (Deactivated for now)

- **Storage**: MinIO S3-compatible server running in Docker
- **Access**: `http://localhost:9000`
- **Console**: `http://localhost:9001` (minioadmin/minioadmin123)
- **URLs**: `http://localhost:9000/maple-quest-images/...`
- **Benefits**: No AWS costs, offline development, faster uploads

### Deployment:

**Local Development:**

```bash
make up  # Starts MinIO automatically
```

### Health Check

```bash
GET /health/
```

Returns server health status and database connectivity.

## Connecting to the Database

- The application is configured to connect to a PostgreSQL database created as a Docker service named `db`.

## API Quick Reference


### User & Profile

| Endpoint               | Method | Auth | Description           |
| ---------------------- | ------ | ---- | --------------------- |
| `/auth/register/`      | POST   | ❌   | Register new user     |
| `/auth/login/`         | POST   | ❌   | Login user            |
| `/auth/token/refresh/` | POST   | ❌   | Refresh JWT token     |
| `/api/users/me/`       | GET    | ✅   | Get current user      |


## Authentication Notes

- All authenticated endpoints require the `Authorization: Bearer <token>` header
- Access tokens expire after 1 hour
- Refresh tokens expire after 7 days
- Use `/auth/token/refresh/` to get a new access token
- Tokens are returned on registration and login
