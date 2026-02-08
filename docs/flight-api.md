Flight API integration (v1)

Provider
- Amadeus (recommended)
- Fallbacks: Skyscanner, Kiwi

Concerns
- Rate limiting
- Data freshness
- Price currency conversion

Client outline
- Auth handling (token refresh)
- Search request builder
- Response parsing to internal model
- Error mapping to API responses

Reliability
- Retry on transient errors
- Circuit break for provider outages
- Cache identical searches (short TTL)
