import requests
import time

# --- CONFIGURATION ---
DATASET_UUID = "2751aacf-5472-4850-a208-3532a51c529a"
EMAIL = "sebastian.arnesen@gmail.com"

def place_order(email, uuid):
    url = "https://nedlasting.geonorge.no/api/order"
    
    # Using the structure that successfully returned a referenceNumber
    order_payload = {
        "email": email,
        "usage": "Prototyping for a startup",
        "orderLines": [
            {
                "metadataUuid": uuid,
                "areas": [{"code": "03", "type": "fylke"}], 
                "formats": [{"name": "FGDB"}],
                "projections": [{"code": "25833"}]
            }
        ]
    }

    print("Sending order request...")
    response = requests.post(url, json=order_payload)

    if response.status_code in [200, 201, 211]:
        return response.json().get("referenceNumber")
    else:
        print(f"Failed to place order. Status: {response.status_code}")
        print(response.text)
        return None

def monitor_order(order_id):
    status_url = f"https://nedlasting.geonorge.no/api/order/{order_id}"
    print(f"Monitoring order: {order_id}")
    
    start_time = time.time()
    
    while True:
        response = requests.get(status_url)
        
        if response.status_code != 200:
            print(f"Server busy (Status: {response.status_code}). Retrying...")
            time.sleep(10)
            continue
            
        data = response.json()
        if isinstance(data, list):
            data = data[0]

        # The API doesn't provide a 'status' key in this view.
        # We check if the 'files' list has been populated yet.
        files = data.get("files", [])
        
        if files:
            # Success! The server has finished packing the data.
            download_url = files[0].get("downloadUrl")
            print(f"\nSUCCESS! Data is ready after {int(time.time() - start_time)} seconds.")
            print(f"Download link: {download_url}")
            return
        else:
            # If 'files' is empty, it's still being processed.
            elapsed = int(time.time() - start_time)
            print(f"Still processing... (Elapsed: {elapsed}s)")
        
        # Nautical data for a whole county can take several minutes to clip.
        time.sleep(20)

if __name__ == "__main__":
    ref_num = place_order(EMAIL, DATASET_UUID)
    if ref_num:
        monitor_order(ref_num)