### Product Scope: The Personalized AI Wealth Copilot
Your goal is to build an intelligent layer on top of a user's trading account. It moves the user experience from a static dashboard ("Here are your numbers") to an interactive, proactive financial relationship.

📍 Foundation: Secure Data & Context (What we just built)
Before the agent can do anything, it needs eyes and ears.

Internal Knowledge: Secure BigQuery tools to read the user's trade history, PNL, and current positions.

External Knowledge: APIs to read live market news and price trends.

#### Stage 1: The Contextual Analyst (Reactive)
Core Function: Real-time financial expert.

User Value: The user no longer has to guess why their portfolio is moving. They can ask, "Why did my crypto drop today?" The agent pulls their positions, checks the market news, and provides a synthesized explanation.

Actionable Output: It provides immediate, data-backed answers and basic suggestions (e.g., "Your exposure to tech stocks is at 80%, which makes your portfolio highly volatile right now").

#### Stage 2: The Behavioral Profiler (Memory Engine)
Core Function: Continuous learning and user profiling.

User Value: The agent starts building a user_memory.md (or a vector database profile) detailing the user's unique "Trading Thesis."

How it works: If the user constantly asks about dividend yields, the agent notes an income-investing bias. If the user panic-sells Bitcoin every time it drops 5%, the agent logs a low risk-tolerance. It tracks their win/loss ratio on specific asset classes and learns how they trade, not just what they trade.

#### Stage 3: The Expert Strategist (Persona & Skills Application)
Core Function: Applying advanced, multi-agent reasoning and expert frameworks.

User Value: Portfolio diagnosis using the minds of legendary investors.

How it works: You give the agent "skills." The agent can cross-reference the user's Stage 2 behavior profile and Stage 1 portfolio data against established frameworks. The user could ask, "Diagnose my portfolio using a Ray Dalio All-Weather approach," or "What would Warren Buffett think of my recent stock picks?" The agent identifies blind spots based on those expert methodologies.