"""
Here’s a concise reading path with solid docs to get you up to speed on the topics affecting your ECS performance and errors.

Start with your app stack

FastAPI async basics and blocking work: https://fastapi.tiangolo.com/async/
Offloading sync work: run_in_threadpool (Starlette): https://www.starlette.io/concurrency/
Concurrency limits in-app (asyncio.Semaphore): https://docs.python.org/3/library/asyncio-sync.html#asyncio.Semaphore
Uvicorn deployment and settings (workers, keep-alive): https://www.uvicorn.org/settings/
AWS specifics you’re likely hitting

ECS/Fargate service basics and task sizing (vCPU/memory): https://docs.aws.amazon.com/AmazonECS/latest/developerguide/what-is-amazon-ecs.html
Application Load Balancer idle timeout (match your server keep-alive): https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-troubleshooting.html#load-balancer-troubleshooting-timeout
Target group health checks (avoid flapping): https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html
CloudWatch logs for containers: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/QuickStartEC2Instance.html
S3 downloads and client tuning

Boto3 client config (max_pool_connections): https://botocore.amazonaws.com/v1/documentation/api/latest/reference/config.html
S3 performance best practices: https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html
aioboto3 (async S3, optional): https://github.com/terrycain/aioboto3
Provider rate limits and retries (if using LLM APIs)

OpenAI rate limits and backoff: https://platform.openai.com/docs/guides/rate-limits
Load testing and sizing

k6 (quick, scriptable): https://k6.io/docs/get-started/running-k6/
Locust (Python-based): https://docs.locust.io/en/stable/what-is-locust.html
Vegeta: https://github.com/tsenart/vegeta
What to search for (keywords)

“FastAPI blocking call in async endpoint”
“Uvicorn workers 1 vCPU”
“ALB idle timeout uvicorn timeout-keep-alive”
“boto3 max_pool_connections S3 concurrency”
“asyncio semaphore rate limiting”
If you share your ECS task definition (CPU/mem), how you start Uvicorn in the container, and sample error codes from logs (e.g., 502/504/5xx/429), I can point to the exact docs and settings to change.

Node.js process events (unhandledRejection, uncaughtException)
https://nodejs.org/api/process.html#event-unhandledrejection
https://nodejs.org/api/process.html#event-uncaughtexception
Node.js promise rejection handling policy (historical context)
https://nodejs.org/en/blog/release/v15.0.0/#throw-on-unhandled-rejections
MDN Promises and error propagation
https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise
NestJS Exception Filters & Error Handling
https://docs.nestjs.com/exception-filters
NestJS Logging
https://docs.nestjs.com/techniques/logger
NestJS WebSockets (for job status push)
https://docs.nestjs.com/websockets/gateways
Fire‑and‑forget pitfalls (example discussion)
https://stackoverflow.com/questions/31413749/node-js-fire-and-forget
AWS ALB 502/503 troubleshooting (upstream unhealthy / crash)
https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-troubleshooting.html
AWS ECS task health & restarts (if you use ECS/Fargate)
https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-event-messages.html
API Gateway 5XX errors (if using API Gateway)
https://docs.aws.amazon.com/apigateway/latest/developerguide/monitoring-error.html
Resilience patterns (timeouts, retries, circuit breakers)
https://learn.microsoft.com/azure/architecture/patterns/circuit-breaker
Bull / BullMQ (if you later adopt a real queue)
https://docs.bullmq.io/
Twelve-Factor App (disposability & crash behavior)
https://12factor.net/
Backpressure & event loop blocking (to avoid cascading failures)
https://nodejs.org/en/docs/guides/event-loop-timers-and-nexttick


"""

"""
Resources to Learn About FastAPI Middleware & Response Handling
Here are the best resources to understand this code:

1. Official FastAPI Documentation
Middleware:
FastAPI Middleware Guide: https://fastapi.tiangolo.com/tutorial/middleware/
Advanced Middleware: https://fastapi.tiangolo.com/advanced/middleware/
Request & Response:
Response Models: https://fastapi.tiangolo.com/tutorial/response-model/
Custom Response: https://fastapi.tiangolo.com/advanced/custom-response/
Request Object: https://fastapi.tiangolo.com/advanced/using-request-directly/
2. Starlette Documentation (FastAPI is built on Starlette)
Starlette Middleware: https://www.starlette.io/middleware/
Starlette Responses: https://www.starlette.io/responses/
Background Tasks: https://www.starlette.io/background/
3. Python Async/Await
Official Python Docs:
Async IO: https://docs.python.org/3/library/asyncio.html
Async Iterators: https://docs.python.org/3/reference/datamodel.html#asynchronous-iterators
Real Python Tutorials:
Async IO in Python: https://realpython.com/async-io-python/
AsyncIO for Beginners: https://realpython.com/python-async-features/
4. HTTP Fundamentals
MDN HTTP Overview: https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview
HTTP Status Codes: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status
HTTP Headers: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers
5. Specific Topics in Your Code
Response Body Streaming:
Starlette Streaming: https://www.starlette.io/responses/#streamingresponse
Understanding Iterators: https://realpython.com/introduction-to-python-generators/
Logging:
Python Logging: https://docs.python.org/3/howto/logging.html
Real Python Logging: https://realpython.com/python-logging/
Exception Handling:
FastAPI Exceptions: https://fastapi.tiangolo.com/tutorial/handling-errors/
Custom Exception Handlers: https://fastapi.tiangolo.com/tutorial/handling-errors/#install-custom-exception-handlers
6. Practical Learning Path
Beginner:
Read FastAPI Tutorial (start to finish): https://fastapi.tiangolo.com/tutorial/
Learn Python async basics: https://realpython.com/async-io-python/
Understand HTTP fundamentals: https://developer.mozilla.org/en-US/docs/Web/HTTP
Intermediate:
Deep dive into middleware: https://fastapi.tiangolo.com/advanced/middleware/
Study request/response lifecycle: https://www.starlette.io/requests/
Learn about streaming responses: https://www.starlette.io/responses/#streamingresponse
Advanced:
Custom response classes: https://fastapi.tiangolo.com/advanced/custom-response/
Background tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/
Performance optimization: https://fastapi.tiangolo.com/deployment/concepts/
7. Books
"FastAPI - Modern Python Web Development" by Bill Lubanovic
"Using Asyncio in Python" by Caleb Hattingh
"HTTP: The Definitive Guide" by David Gourley
8. Video Tutorials
YouTube Channels:
ArjanCodes - Python async patterns: https://www.youtube.com/@ArjanCodes
mCoding - Advanced Python: https://www.youtube.com/@mCoding
Corey Schafer - Python tutorials: https://www.youtube.com/@coreyms
Specific Videos:
"FastAPI Middleware Explained": Search on YouTube
"Python Async/Await Tutorial": Multiple available
9. Interactive Learning
FastAPI GitHub Examples: https://github.com/tiangolo/fastapi/tree/master/docs_src
Starlette Examples: https://github.com/encode/starlette/tree/master/docs
10. Community Resources
FastAPI Discord: https://discord.gg/fastapi
Stack Overflow: Tag fastapi or starlette
Reddit: r/FastAPI


"""
