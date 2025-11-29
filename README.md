# RSS vijesti za poreze, mirovine i klimatske politike

Mali Streamlit projekt koji pretražuje RSS kanale hrvatskih portala
prema tematskim profilima ključnih riječi.

## Struktura

- `app.py` glavni Streamlit app
- `requirements.txt` Python ovisnosti

## Lokalno pokretanje

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy na Streamlit Cloud

1. Napravi novi GitHub repozitorij i dodaj ove datoteke.
2. Poveži repozitorij na Streamlit Cloudu.
3. Kao entry point navedi `app.py`.
