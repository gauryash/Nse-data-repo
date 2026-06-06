"""
Telegram notification utilities.

Sends text messages and DataFrame chunks to Telegram chats.
"""

import requests
import pandas as pd

from nse_relative.config.settings import BOT_TOKEN, CHAT_ID_ALERT
from nse_relative.config.logger import get_logger

logger = get_logger(__name__)


def send_telegram_message(
    bot_token: str = BOT_TOKEN,
    chat_id: str = CHAT_ID_ALERT,
    message: str = "",
) -> bool:
    """Send a text message to a Telegram chat (Markdown parsing)."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        resp = requests.post(url, data=payload, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Telegram send failed: %s", e)
        return False


def dataframe_to_telegram_chunks(
    df: pd.DataFrame,
    title: str,
    max_rows: int = 20,
    full_df: bool = True,
) -> list[str]:
    """Prepare Telegram messages from a DataFrame.

    If *full_df* is ``True``, render the DataFrame as a monospace table.
    If ``False``, send only the ``'nsecode'`` column as a bullet list.
    """
    if df.empty:
        return [f"*{title}*\n\n_No data to display._"]

    if not full_df:
        names = df["nsecode"].tolist()
        chunks = []
        for i in range(0, len(names), max_rows):
            chunk_list = names[i:i + max_rows]
            text = "\n".join(f"- {code}" for code in chunk_list)
            msg = f"*{title}*\n\n{text}"
            if i + max_rows < len(names):
                msg += f"\n_Showing rows {i+1} to {i+max_rows}…_"
            chunks.append(msg)
        return chunks

    # Full DataFrame mode
    rename_map = {
        "nsecode": "NSE",
        "name": "Name",
        "bsecode": "BSE",
        "per_chg": "%Chg",
        "close": "Close",
        "volume": "Vol",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    chunks = []
    for i in range(0, len(df), max_rows):
        chunk = df.iloc[i:i + max_rows]
        text = chunk.to_string(index=False)
        msg = f"*{title}*\n```\n{text}\n```"
        if i + max_rows < len(df):
            msg += f"\n_Showing rows {i+1} to {i+max_rows}…_"
        chunks.append(msg)

    return chunks
