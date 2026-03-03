import os
import firebase_admin
from firebase_admin import credentials, firestore

def check_db():
    if not firebase_admin._apps:
        cred = credentials.Certificate('firebase_key.json')
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    
    for code in ["7203", "9984", "7267"]:
        d = db.collection('companies').document(code).get()
        if d.exists:
             data = d.to_dict()
             print(f"Code: {d.id}")
             print(f"  Name: {data.get('★企業名', 'N/A')}")
             print(f"  Assets: {data.get('★資産合計', 'N/A')}")
             print(f"  Cash: {data.get('流動_現金及び預金', 'N/A')}")
             print(f"  Doc: {data.get('B/S_取得書類', 'N/A')}")
             
check_db()
