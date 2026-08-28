"""Shared behaviour for API viewsets whose model is scoped to one café."""
from __future__ import annotations


class CafeScopedCreateMixin:
    """Assigns the café on create for any CafeScopedModel viewset.

    A plain non-superuser can only ever create objects in their own café --
    the request body is never trusted for this, whatever it contains.

    A superuser normally administers every café on the server, but the very
    first account on any install (created by `manage.py bootstrap`) is a
    superuser that is *also* the owner of exactly one café. Without this
    mixin, that overwhelmingly common account could not create anything
    through the API at all: `serializer.save()` with no café would either
    violate the not-null constraint outright (Camera) or silently create an
    orphaned, café-less record (User, whose `cafe` is nullable) -- both
    discovered the same way, by actually using the bootstrap-created account
    against a running server rather than only a synthetic test fixture.

    The fix: default to the superuser's own café unless the request body
    explicitly names a different one, which only a genuine platform admin
    managing another tenant would ever need to do.
    """

    def perform_create(self, serializer) -> None:
        user = self.request.user
        if not user.is_superuser:
            serializer.save(cafe_id=user.cafe_id)
        elif "cafe" not in serializer.validated_data and user.cafe_id:
            serializer.save(cafe_id=user.cafe_id)
        else:
            serializer.save()
