#!/usr/bin/env python3
"""
download_datasets.py
Script di automazione per il download e aggiornamento dei dataset sanitari:
- Dataset Principale (Portale Open Data Regione Lazio - dati.lazio.it):
    Pronto Soccorso, Censimento Ospedali, Strutture Sanitarie, Farmacie, Carichi operativi
- Dataset Integrativo (Portale Nazionale Open Data - dati.gov.it):
    Tempi di attesa, Prestazioni specialistiche ambulatoriali, Flussi sanitari
"""

import os
import sys
import csv
import json
import urllib.request
import urllib.error

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '2-data', 'raw'))
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# 1. DATASET PRINCIPALE (dati.lazio.it) - API Datastore
PRINCIPALE_DATASTORE = {
    'dataset_principale/lazio/pronto_soccorso_accessi_tempo_reale.csv': {
        'resource_id': '12c31624-f1a4-4874-a903-8954549ddb81',
        'desc': 'Pronto Soccorso - Accessi in tempo reale (triage, codici colore, presidi e ASL)'
    },
    'dataset_principale/lazio/elenco_ospedali_lazio.csv': {
        'resource_id': '0219ed0b-5f99-47a3-be27-9df0d108ff6f',
        'desc': 'Elenco degli ospedali del Lazio (censimento strutture e ASL)'
    },
    'dataset_principale/lazio/strutture_sanitarie_private_accreditate.csv': {
        'resource_id': '1a59e29a-da23-4fb9-8b14-78289f3333cb',
        'desc': 'Elenco delle strutture sanitarie private accreditate'
    },
    'dataset_principale/lazio/ps_accessi_triage_storico.csv': {
        'resource_id': '48741c74-3c2a-4650-a764-414bf998e379',
        'desc': 'Numero di accessi al Pronto Soccorso per triage (P.Re.Val.E.)'
    },
}

# 2. DATASET PRINCIPALE (dati.lazio.it) - Download diretti
PRINCIPALE_DIRECT = {
    'dataset_principale/lazio/farmacie_regione_lazio.csv': {
        'url': 'https://dati.lazio.it/dataset/551579e1-a65d-4e7e-80d7-9bfe07fb2bdc/resource/7658322d-b629-4d77-a9f1-e4aad7c8f83b/download/farmaciereglaziolatlon.csv',
        'desc': 'Farmacie territoriali Regione Lazio con geolocalizzazione Lat/Lon'
    },
    'dataset_principale/lazio/parafarmacie_regione_lazio.csv': {
        'url': 'https://dati.lazio.it/dataset/886075d1-b5a6-4ee8-ae74-38febaf74108/resource/55f2c0d3-7860-42bb-8f04-c99d2f4ddd1e/download/parafarmaciereglazio.csv',
        'desc': 'Parafarmacie della Regione Lazio'
    },
    'dataset_principale/lazio/ps_durata_permanenza_storico.csv': {
        'url': 'https://dati.lazio.it/dataset/f9198f21-02b8-4479-bccc-eff18564fa8f/resource/27d6bbec-2035-4352-8439-2e2aaed2b907/download/pspermanenza.csv',
        'desc': 'Numero di accessi al Pronto Soccorso per durata di permanenza'
    },
    'dataset_principale/lazio/meteo/termolug22.csv': {
        'url': 'https://dati.lazio.it/dataset/4233ea5a-2a0c-4951-9405-b43f32fdf646/resource/3eeddf96-ca20-4502-ace9-ec2278475146/download/termolug22.csv',
        'desc': 'Serie storica temperature stazioni meteo Lazio - Luglio 2022'
    },
}

# 3. DATASET INTEGRATIVO (dati.gov.it) - Download diretti
INTEGRATIVO_DIRECT = {
    'dataset_integrativo/nazionale/tempi_attesa_ambulatoriali_correnti.csv': {
        'url': 'https://dati.regione.umbria.it/dataset/d85cf129-a64e-4d3a-94c1-f4601f4c6bf4/resource/13e0c38e-7fa2-4b46-a720-03d664abb01a/download/agg_monitoraggio_ta.csv',
        'desc': 'Monitoraggio tempi di attesa prestazioni specialistiche ambulatoriali (classi U, B, D, P)'
    },
    'dataset_integrativo/nazionale/tempi_attesa_ambulatoriali_storico.csv': {
        'url': 'https://dati.regione.umbria.it/dataset/d85cf129-a64e-4d3a-94c1-f4601f4c6bf4/resource/9cb66e06-4362-4323-9a85-c026f8f725dc/download/agg_monitoraggio_ta_storico.csv',
        'desc': 'Serie storiche tempi di attesa prestazioni specialistiche ambulatoriali'
    },
    'dataset_integrativo/nazionale/monitoraggio_tempi_attesa_settimanale.csv': {
        'url': 'https://dati.puglia.it/ckan/dataset/8d6b91a6-9575-4dba-b4f0-f8771ce08825/resource/ce27e2e3-69b2-43b2-b300-7023ed3479f3/download/monitoraggio-tempi-di-attesa-09_13-gennaio-2023.csv',
        'desc': 'Monitoraggio tempi attesa settimanale per codice prestazione e ASL'
    },
    'dataset_integrativo/nazionale/flussi_ambulatoriali_ex_post.csv': {
        'url': 'https://dati.puglia.it/ckan/dataset/9b3876cc-e2d8-4505-ba02-ec4f7c090d60/resource/9dc0130f-1f15-489b-9f52-49b22a09230b/download/monitoraggio-ex-ante-istituzionale.csv',
        'desc': 'Monitoraggio CUP flussi sanitari ed erogazioni prestazioni ambulatoriali'
    },
    'dataset_integrativo/nazionale/catalogo_discipline_ambulatoriali.xlsx': {
        'url': 'https://dati.regione.marche.it/dataset/b0b4713d-73b5-4180-9677-c277e2f623d7/resource/1fe2ae65-9fc8-4210-ba7b-1c4da0936972/download/discipline.xlsx',
        'desc': 'Catalogo discipline specialistiche ambulatoriali'
    },
    'dataset_integrativo/nazionale/catalogo_branche_ambulatoriali.xlsx': {
        'url': 'https://dati.regione.marche.it/dataset/b0b4713d-73b5-4180-9677-c277e2f623d7/resource/df33b789-e44a-4cc4-984a-d2695ea2913b/download/branche.xlsx',
        'desc': 'Catalogo branche specialistiche ambulatoriali'
    }
}


def download_datastore(resource_id, dest_path, limit=5000):
    url = f'https://dati.lazio.it/api/3/action/datastore_search?resource_id={resource_id}&limit={limit}'
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        records = data['result']['records']
        fields = [f['id'] for f in data['result']['fields'] if f['id'] != '_id']
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(records)
        return len(records), os.path.getsize(dest_path)


def download_file(url, dest_path):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with urllib.request.urlopen(req, timeout=15) as resp, open(dest_path, 'wb') as f:
        f.write(resp.read())
    return os.path.getsize(dest_path)


def main():
    print("==================================================")
    print("  DOWNLOAD & AGGIORNAMENTO DATASET SANITARI")
    print("==================================================")
    
    print("\n--- [A] DATASET PRINCIPALE (dati.lazio.it) ---")
    for rel_path, meta in PRINCIPALE_DATASTORE.items():
        dest = os.path.join(BASE_DIR, rel_path)
        try:
            records, size = download_datastore(meta['resource_id'], dest)
            print(f"  [OK] {rel_path}: {records} record, {size:,} bytes")
        except Exception as e:
            print(f"  [ERRORE] {rel_path}: {e}")

    for rel_path, meta in PRINCIPALE_DIRECT.items():
        dest = os.path.join(BASE_DIR, rel_path)
        try:
            size = download_file(meta['url'], dest)
            print(f"  [OK] {rel_path}: {size:,} bytes")
        except Exception as e:
            print(f"  [ERRORE] {rel_path}: {e}")

    print("\n--- [B] DATASET INTEGRATIVO (dati.gov.it) ---")
    for rel_path, meta in INTEGRATIVO_DIRECT.items():
        dest = os.path.join(BASE_DIR, rel_path)
        try:
            size = download_file(meta['url'], dest)
            print(f"  [OK] {rel_path}: {size:,} bytes")
        except Exception as e:
            print(f"  [ERRORE] {rel_path}: {e}")

    print("\n=== Download e organizzazione completati! ===")


if __name__ == '__main__':
    main()
