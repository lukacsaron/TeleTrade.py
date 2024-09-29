# Telegram Trading Signal Monitoring and Trade Execution Tracking App

## Overview

This app monitors multiple Telegram channels for trading signals, parses them using the OpenAI API to understand natural language inputs, and stores them in a MongoDB database. Each signal is assigned a unique identifier (`signal_id`), which is used to track the corresponding trade execution. The app records the execution status of trades, including order placements, fulfillment statuses, and trade closures.

## Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/telegram_signal_monitor.git
cd telegram_signal_monitor
