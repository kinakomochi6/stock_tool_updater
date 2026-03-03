import os
import firebase_admin
from firebase_admin import credentials, firestore

def check_db():
    if not firebase_admin._apps:
        cred = credentials.Certificate('firebase_key.json')
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    
    # Query an explicit J-GAAP company. Say, 7201 Nissan (usually J-GAAP? Wait, Nissan might be IFRS).
    # Take 8031 Mitsui & Co. (IFRS), 6758 Sony (IFRS).
    # Let's take some standard ones: 6396 (J-GAAP), 9432 (NTT - IFRS), 7201
    for code in ["6396", "4333", "7974"]:
        d = db.collection('companies').document(code).get()
        if d.exists:
             data = d.to_dict()
             print(f"Code: {d.id}")
             print(f"  Name: {data.get('★企業名', 'N/A')}")
             print(f"  Assets: {data.get('★資産合計', 'N/A')}")
             print(f"  Doc: {data.get('B/S_取得書類', 'N/A')}")
             
check_db()
