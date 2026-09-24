import asyncio
import httpx

BASE_URL = "http://127.0.0.1:8000/api"

async def test_api_workflow():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Test Super Admin Login
        print("Testing Super Admin Login...")
        resp = await client.post("/auth/login", json={
            "email": "superadmin@swipee.test",
            "password": "password"
        })
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == "superadmin@swipee.test"
        assert data["user"]["role"] == "super_admin"
        superadmin_token = data["token"]
        print("  Super Admin Login: PASSED")

        # 2. Test /me
        print("Testing /auth/me for Super Admin...")
        resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {superadmin_token}"})
        assert resp.status_code == 200, f"Me failed: {resp.text}"
        me_data = resp.json()
        assert me_data["role"] == "super_admin"
        assert len(me_data["permissions"]) > 20
        print("  Super Admin /me: PASSED (Has all permissions)")

        # 3. Test Merchant Login
        print("Testing Merchant Login...")
        resp = await client.post("/auth/login", json={
            "email": "owner@trendsetter.test",
            "password": "password"
        })
        assert resp.status_code == 200, f"Merchant login failed: {resp.text}"
        merchant_data = resp.json()
        assert merchant_data["user"]["role"] == "merchant"
        assert merchant_data["user"]["merchant"]["slug"] == "trendsetter"
        merchant_token = merchant_data["token"]
        print("  Merchant Login: PASSED")

        # 4. Test Merchant Products
        print("Testing Merchant Products list...")
        resp = await client.get("/merchant/products", headers={"Authorization": f"Bearer {merchant_token}"})
        assert resp.status_code == 200, f"Products failed: {resp.text}"
        prods = resp.json()["data"]
        assert len(prods) > 0
        print(f"  Merchant Products: PASSED ({len(prods)} products found)")

        # 5. Test Taxonomy
        print("Testing Categories & Attributes...")
        resp = await client.get("/taxonomy/categories", headers={"Authorization": f"Bearer {merchant_token}"})
        assert resp.status_code == 200
        cats = resp.json()
        assert len(cats) > 0
        print(f"  Taxonomy Categories: PASSED ({len(cats)} categories)")

        # 6. Test Dashboard
        print("Testing Dashboard metrics...")
        resp = await client.get("/dashboard", headers={"Authorization": f"Bearer {merchant_token}"})
        assert resp.status_code == 200
        dash = resp.json()
        assert dash["role"] == "merchant"
        assert "kpis" in dash
        print(f"  Dashboard: PASSED (Total products: {dash['kpis']['total_products']})")

        # 7. Test Admin Product Review Queue
        print("Testing Admin Review Queue...")
        resp = await client.get("/admin/products/queue", headers={"Authorization": f"Bearer {superadmin_token}"})
        assert resp.status_code == 200
        print("  Admin Review Queue: PASSED")

        print("\nALL API WORKFLOW TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_api_workflow())
