import clerk_backend_api
from clerk_backend_api.security.types import AuthenticateRequestOptions

class Req:
    def __init__(self):
        self.headers = {"authorization": "Bearer garbage"}
        self.url = "http://localhost/"

clerk = clerk_backend_api.Clerk(bearer_auth="sk_test_fake")
state = clerk.authenticate_request(Req(), AuthenticateRequestOptions())
print(state.is_signed_in)
print(state.message)
