from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory limiter: fine for a single-process deployment. If this app ever
# runs multiple worker processes/instances behind a load balancer, back this
# with Redis (slowapi supports storage_uri="redis://...") so limits are
# shared across processes instead of tracked separately per worker.
limiter = Limiter(key_func=get_remote_address)
