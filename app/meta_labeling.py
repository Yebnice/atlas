from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from .strategy_engine import strategy_signals

META_FEATURES = ["ensemble","trend","momentum","breakout","mean_reversion","adx","rsi","realized_vol"]

def build_meta_dataset(df: pd.DataFrame, *, horizon: int = 3, min_edge_bps: float = 10.0):
    sig = strategy_signals(df)
    close = df["close"].astype(float)
    future = close.shift(-horizon) / close - 1.0
    direction = np.sign(sig["ensemble"].astype(float))
    edge = future * direction
    y = (edge > float(min_edge_bps) / 10000.0).astype(int)
    X = sig[META_FEATURES].replace([np.inf,-np.inf],np.nan)
    valid = X.notna().all(axis=1) & future.notna() & (direction != 0)
    return X.loc[valid], y.loc[valid]

def meta_label_walk_forward(df: pd.DataFrame, *, horizon: int = 3, min_edge_bps: float = 10.0, folds: int = 5, threshold: float = 0.55) -> dict:
    X,y=build_meta_dataset(df,horizon=horizon,min_edge_bps=min_edge_bps)
    if len(X)<250 or y.nunique()<2: return {"status":"INSUFFICIENT_DATA","observations":int(len(X))}
    splits=np.array_split(np.arange(len(X)), max(2,min(folds, len(X)//50)))
    oos=[]
    probs=[]
    for i in range(1,len(splits)):
        tr=np.concatenate(splits[:i]); te=splits[i]
        if len(tr)<100 or y.iloc[tr].nunique()<2: continue
        model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=500,class_weight="balanced",random_state=7))
        model.fit(X.iloc[tr],y.iloc[tr])
        p=model.predict_proba(X.iloc[te])[:,1]
        probs.extend(p.tolist())
        oos.extend((p>=float(threshold)).astype(int).tolist())
    # Predict the CURRENT, unlabeled bar. The last labelled observation is
    # horizon bars behind the current bar, so using X.iloc[-1] here would make
    # the live gate stale. The current feature vector is never used as a training
    # label because its future outcome does not yet exist.
    latest_model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=500,class_weight="balanced",random_state=7))
    latest_model.fit(X,y)
    current_sig = strategy_signals(df)[META_FEATURES].replace([np.inf,-np.inf],np.nan)
    current = current_sig.iloc[[-1]]
    if current.isna().any(axis=None):
        return {"status":"CURRENT_FEATURES_UNAVAILABLE","observations":int(len(X)),"oos_observations":int(len(oos)),"execution_authority":False}
    latest=float(latest_model.predict_proba(current)[0,1])
    return {"status":"OK","observations":int(len(X)),"oos_observations":int(len(oos)),"oos_take_rate":float(np.mean(oos)) if oos else 0.0,"current_probability":latest,"latest_probability":latest,"threshold":float(threshold),"horizon_bars":horizon,"min_edge_bps":min_edge_bps,"training_last_label_index":str(X.index[-1]) if len(X) else None,"prediction_index":str(current.index[-1]),"current_prediction_is_oos":True,"execution_authority":False}

def meta_label_gate(df: pd.DataFrame, *, horizon: int = 3, min_edge_bps: float = 10.0, threshold: float = 0.55) -> dict:
    result=meta_label_walk_forward(df,horizon=horizon,min_edge_bps=min_edge_bps,threshold=threshold)
    if result.get("status")!="OK": return {**result,"take_trade":False}
    p=float(result.get("latest_probability",0.0))
    return {**result,"take_trade":p>=float(threshold)}
