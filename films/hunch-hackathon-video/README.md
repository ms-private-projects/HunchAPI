# Hunch hackathon film

`hunch-hackathon.mp4` is the three-minute cut made for the Meta Global AI Developer Hackathon
judges (1920×1080) and `poster.jpg` its still. It keeps the marketing film's opening and its
Muse-app scene ([`../hunch-demo-video`](../hunch-demo-video)) and replaces everything between
with real screens of the product and a chapter on how Hunch uses Muse:

- **Critique, research, build, funding, the daily review and the leaderboard are captures of the
  Hunch site** on the local stack, for the take "AI needs power" created for the film: the thesis
  critique arriving from Muse Spark 1.3 (27.7 s), research 1 by Muse Wonder 1.0 (42.3 s: 6 claims,
  8 candidates with roles, 65 cited evidence items), the basket the guardrails built from it
  (NextEra and Vistra capped at the 15% limit, 10% cash), the real Alpaca paper account linked
  through the hosted connector, a $10,000 funding whose eight orders filled on Hunch's simulated
  venue, the daily review Muse Spark 1.3 answered in 17.5 s ("hold"), and the published take on
  the leaderboard. Daily prices on that stack are synthetic, and the end card says so.
- **"Under the hood"** names the four jobs and the two models, the Meta Model API, the schema
  bounds, the recorded request and the test that pins every deployed model call to Muse.
- The opening, the take form and the Muse-app scene are styled cards, as in the marketing cut;
  "Hunch inside the Muse app" is labelled coming soon.

`hunch-live-run.mp4` (2:42, 6.8 MB) is a separate, unedited screen recording of the local stack
made with `tools/capture/record.cjs` (Chrome's screencast through puppeteer, frames assembled at
their real timestamps): one take from a new thesis to a filled proposal on the simulated venue, with
the UTC clock and the elapsed time burned in. It is also on YouTube, unlisted:
https://youtu.be/QQTfoTPIWJg.

The film was made as a [HyperFrames](https://hyperframes.heygen.com) project (HTML and CSS
animated with GSAP). The project, its captures and media stay on the team's machines; only this cut
is committed. The voice is a Fish Audio Drama 3 voice invented for the film (no real person
cloned); the music was generated with ACE-Step 1.5. The Alpaca, Interactive Brokers, Meta and Muse
logos belong to their owners, and no partnership is implied.
