
import asyncio
import csv
import time

import yfinance as yf
import requests

import os
from pathlib import Path

from backend.models.db_models import Company, Document, FinancialMetric

from sqlalchemy.ext.asyncio import AsyncSession
from backend.services.postgres_service import AsyncSessionLocal, engine

CSV_PATH = Path(__file__).parent / "companies.csv"
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")


def fetch_yahoo_data(ticker: str) -> dict | None:
    try:
        #print(dir(yf))
        stock = yf.Ticker(ticker)
        info = stock.info
        print("info=",info)
        name = info.get("longName") or info.get("shortName")

        if not name:
            print(f" Skipping {ticker} - no data found")
            return None
        return {
            "name": name,
            "sector": info.get("sector", "Unknown"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "revenue_growth": info.get("revenueGrowth"),
        }

    except Exception as e:
        print(f"  Error fetching {ticker} from Yahoo: {e}")
        return None

def fetch_alpha_vantage_news(ticker: str) -> list[dict]:
    try:
        url = (
          f"https://www.alphavantage.co/query"
          f"?function=NEWS_SENTIMENT"
          f"&tickers={ticker}"
          f"&limit=3"
          f"&apikey={ALPHA_VANTAGE_KEY}"
        )
        response = requests.get(url, timeout=10)
        data = response.json()
        articles = []
        for item in data.get("feed", [])[:3]:
            articles.append({
                "content": item.get("summary",item.get("title","")),
                "doc_type": "news",
                "source": item.get("source", "Alpha Vantage")
            })
        return articles

    except Exception as e:
        print(f" Alpha Vantage news failed for {ticker}: {e}")
        return []

async def seed():
    # Create one async database session for the seeding operation
    async with AsyncSessionLocal() as db:
        try:
            print("Clearing existing data...")

            # Delete child records before parent records
            await db.query(Document).delete()
            await db.query(FinancialMetric).delete()
            await db.query(Company).delete()
            await db.commit()

            with open(CSV_PATH, newline="") as f:
                reader = csv.DictReader(f)
                companies = list(reader)

            print(f" Seeding {len(companies)} companies...\n")

            for row in companies:
                ticker = row["ticker"]
                print(f"  Processing {ticker}...")

                # yfinance is synchronous, so run it in a worker thread
                data = await asyncio.to_thread(fetch_yahoo_data, ticker)
                if not data:
                    continue

                company = Company(
                    name=data["name"],
                    ticker=ticker,
                    sector=data["sector"],
                    market_cap=data["market_cap"],
                )
                db.add(company)
                
                 # Send the company insert so company.id becomes available
                await db.flush()

                metrics = FinancialMetric(
                    company_id=company.id,
                    pe_ratio=data["pe_ratio"],
                    eps=data["eps"],
                    revenue_growth=data["revenue_growth"],
                )
                db.add(metrics)

                # requests is synchronous, so run it in a worker thread
                articles = await asyncio.to_thread(
                    fetch_alpha_vantage_news,
                    ticker,
                )

                for article in articles:
                    doc = Document(
                        company_id=company.id,
                        content=article["content"],
                        doc_type=article["doc_type"],
                        source=article["source"],
                    )
                    db.add(doc) 

                print(f"  {data['name']} | PE: {data['pe_ratio']} | EPS: {data['eps']} | Docs: {len(articles)}")

                await asyncio.sleep(12) 

            await db.commit()
            print(f"\n Done! Database seeded successfully.")
        except:
            await db.rollback()
            raise

        

if __name__=="__main__":
    seed()



