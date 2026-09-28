/**
 * ReturnLess - Client-side helper for the real ML prediction endpoint.
 *
 * There used to be a hand-written scoring formula duplicated here in the
 * browser (customer type, COD payment method, shipping distance, and a
 * hardcoded override for "order #1025"). That entire fake engine has been
 * removed. The only source of a return-probability number in this app is
 * now the trained model on the server, reached via POST /predict-return
 * (see ml/train_model.py + ml/predictor.py). This file just wraps that
 * call so app.js doesn't repeat the fetch boilerplate everywhere.
 */
const PredictionEngine = {
  async predict(productData) {
    const res = await fetch('/predict-return', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(productData)
    });
    return res.json();
  }
};
