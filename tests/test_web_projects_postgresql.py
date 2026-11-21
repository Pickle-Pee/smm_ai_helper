import asyncio
import uuid

from sqlalchemy import delete, func, select, update

from app.db import get_session
from app.main import app
from app.models import BrandProfile, Membership, Organization, User
from tests.postgresql_support import mvp_database
from tests.test_web_auth_postgresql import actors, call
from tests.test_web_session_http import ORIGIN, client, configured, validate
from app.services import web_auth


def test_projects_and_tenant_boundaries(mvp_database, actors, configured, monkeypatch):
    async def database():
        async with mvp_database() as db:
            yield db
    monkeypatch.setitem(app.dependency_overrides, get_session, database)

    async def login(browser, actor):
        browser.headers["Origin"] = ORIGIN
        token = {"token": (await call(mvp_database, web_auth.issue, actor)).secret}
        challenge = await browser.post("/v2/auth/telegram/challenge", json=token)
        await call(mvp_database, web_auth.confirm, actor, challenge.json()["confirmation_code"])
        response = await browser.post("/v2/auth/telegram/exchange", json=token)
        validate("AuthSession", response.json())
        browser.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return response.json()["me"]

    async def run():
        async with client() as owner, client() as stranger:
            me = await login(owner, actors[0])
            await login(stranger, actors[1])
            uid = me["user"]["id"]
            org = me["memberships"][0]["organization"]["id"]
            endpoint = f"/v2/orgs/{org}/projects"
            validate("OrganizationList", (await owner.get("/v2/orgs")).json())
            initial = (await owner.get(endpoint)).json()
            validate("ProjectList", initial)
            assert len(initial["items"]) == 1
            assert (await stranger.get(endpoint)).status_code == 404
            body = {"name": "Another project", "brand": {"extra": {"industry": "Books"}}}
            headers = {"Idempotency-Key": str(uuid.uuid4())}
            replies = await asyncio.gather(*(owner.post(endpoint, json=body, headers=headers) for _ in range(2)))
            assert sorted(r.status_code for r in replies) == [200, 201]
            project = replies[0].json()
            validate("Project", project)
            assert project == replies[1].json()
            assert (await owner.post(endpoint, json={"name": "Conflict"}, headers=headers)).status_code == 409
            first = (await owner.get(endpoint, params={"limit": 1})).json()
            second = (await owner.get(endpoint, params={"limit": 1, "cursor": first["next_cursor"]})).json()
            assert first["items"][0]["id"] != second["items"][0]["id"] and second["next_cursor"] is None
            path = "/v2/projects/" + project["id"]
            brand = path + "/brand"
            for target in (path, brand):
                assert (await stranger.get(target)).status_code == 404
            assert (await stranger.patch(brand, json={"expected_version": 1, "tone": "x"})).status_code == 404
            assert (await owner.patch(path, json={"expected_version": 1, "org_id": org})).status_code == 422
            assert (await owner.patch(path, json={"expected_version": 1, "name": "Edited"})).status_code == 200
            assert (await owner.patch(path, json={"expected_version": 1, "name": "Race"})).status_code == 409
            edited = await owner.patch(brand, json={"expected_version": 1, "extra": {"usp": "New"}})
            validate("ProjectBrand", edited.json())
            assert edited.json()["extra"]["industry"] == "Books"
            confirm = {"expected_version": 2, "confirm_overwrite": True}
            assert (await owner.post(brand + "/import-telegram", json=confirm)).json()["code"] == "import_source_missing"
            async with mvp_database.begin() as db:
                db.add(BrandProfile(user_id=uid, brand_name="Source"))
            try:
                copied = (await owner.post(brand + "/import-telegram", json=confirm)).json()
                validate("ProjectBrand", copied)
                assert copied["imported_from"]["imported_by"]["is_self"]
                confirm["expected_version"] = 3
                assert (await owner.post(brand + "/import-telegram", json=confirm)).json()["code"] == "feature_disabled"
            finally:
                async with mvp_database.begin() as db:
                    await db.execute(delete(BrandProfile).where(BrandProfile.user_id == uid))
            team = uuid.uuid4()
            async with mvp_database.begin() as db:
                db.add(Organization(id=team, kind="team", name="Test team"))
                await db.flush()
                db.add(Membership(org_id=team, user_id=uid, role="editor"))
            try:
                result = await owner.post(f"/v2/orgs/{team}/projects", json=body)
                target = "/v2/projects/" + result.json()["id"]
                async with mvp_database.begin() as db:
                    await db.execute(update(Membership).where(Membership.org_id == team).values(role="viewer"))
                assert (await owner.get(target)).json()["role"] == "viewer"
                forbidden = await owner.patch(target, json={"expected_version": 1, "name": "Fails"})
                assert forbidden.status_code == 403 and forbidden.json()["code"] == "forbidden"
                async with mvp_database.begin() as db:
                    await db.execute(update(Membership).where(Membership.org_id == team).values(revoked_at=func.now()))
                assert (await owner.get(target)).status_code == 404
            finally:
                async with mvp_database.begin() as db:
                    await db.execute(delete(Organization).where(Organization.id == team))
    asyncio.run(run())
