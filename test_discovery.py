from scripts.hap.hap_api_client import HapClient

def test():
    try:
        client = HapClient()
        print("Initial auth:", client.auth)
        # 发起一个简单的请求，比如列出分组
        # GET /v1/open/group/getGroupList
        print("\nAttempting to call getGroupList...")
        groups = client.request("GET", "/v1/open/group/getGroupList")
        print(f"\nSuccess! Found {len(groups)} groups.")
        print("\nFinal auth (should have project_id):", client.auth)
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    test()
