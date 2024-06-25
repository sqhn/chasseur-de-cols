import os

import streamlit as st
import pandas as pd
import time

from dotenv import load_dotenv

import polyline
import folium
import geopandas
import shapely

from stravalib.client import Client
import streamlit_folium

load_dotenv()

st.set_page_config(
    page_title="Chasseur de cols",
    menu_items={
        "Report a bug": "mailto:steven@qhn.fr",
        "About": "Réalisé par Steven Quehan. https://www.qhn.fr",
    }
)

st.image("chasseur_de_cols.png")
st.write("""
Grâce à vos données Strava, Chasseur de cols identifie tous les cols où vous êtes passé. 
""")

client = Client()

# @st.cache_data(ttl=3600)
def get_strava_access_token():
    get_params = st.query_params

    if not get_params.get("code"):
        authorized_url = client.authorization_url(client_id=os.getenv("strava_client_id"), redirect_uri=os.getenv("strava_redirect_uri"))
        st.markdown(f"<a href=\"{authorized_url}\" target=\"_blank\"><img src=\"app/static/btn_strava_connectwith_orange.png\"/></a>", unsafe_allow_html=True)
        st.stop()

    token = client.exchange_code_for_token(client_id=os.getenv("strava_client_id"), client_secret=os.getenv("strava_client_secret"), code=get_params["code"])
    st.query_params.clear()
    return token

if "strava_token" not in st.session_state:
    st.session_state["strava_token"] = get_strava_access_token()
strava_token = st.session_state["strava_token"]

client.access_token = strava_token["access_token"]
client.refresh_token = strava_token["refresh_token"]
client.token_expires_at = strava_token["expires_at"]

# @st.cache_data
def get_cols(cyclist_only=False):
    cols = pd.read_csv("cols.csv")
    cols = geopandas.GeoDataFrame(
        cols, 
        geometry=geopandas.points_from_xy(cols.lng, cols.lat)
    )

    cols["latlng"] = cols.apply(lambda r: [r["lat"], r["lng"]], axis=1)
    
    if cyclist_only:
        cols = cols[cols.est_cycliste]

    cols.index.name = "col_id"

    return cols

# @st.cache_data
def get_activities(limit=None, details=False):
    def get_polyline(id):
        activity = client.get_activity(id)
        return polyline.decode(activity.map.polyline)

    def get_linestring(polyline):
        if len(polyline)>=2:
            lnglat = [latlng[::-1] for latlng in polyline]
            return shapely.LineString(lnglat).buffer(0.002)
        return None

    activities = []
    placeholder = st.empty()
    iterator = client.get_activities(limit=limit)
    for activity in iterator:
        activities.append(activity)
        with placeholder.container():
            st.write(f"Nous chargeons vos activités... {len(activities)}")
    placeholder.empty()
    time.sleep(1)
    

    activities = pd.DataFrame([{
            "activity_id": activity.id,
            "name" : activity.name,
            "distance" : activity.distance,
            "total_elevation_gain" : activity.total_elevation_gain,
            "type" : activity.type,
            "sport_type" : activity.sport_type,
            "start_date" : activity.start_date,
            "start_date_local" : activity.start_date_local,
            "start_latlng" : activity.start_latlng,
            "end_latlng": activity.end_latlng,
            "map_id": activity.map.id,
            "summary_polyline": polyline.decode(activity.map.summary_polyline),
            "polyline": polyline.decode(activity.map.summary_polyline),
        } for activity in activities])

    activities = activities[activities["type"] == "Ride"]
    activities["start_date"] = pd.to_datetime(activities["start_date"]).dt.date
    activities["start_year"] = pd.to_datetime(activities["start_date"]).dt.year

    if details:
        activities["polyline"] = activities.id.apply(get_polyline)

    activities = geopandas.GeoDataFrame(
        activities, 
        geometry=activities.polyline.apply(get_linestring)
    )

    activities.set_index("activity_id", inplace=True)

    return activities

def match_cols(cols, activities):
    cols_matched = activities.sjoin(cols.reset_index(), predicate="contains")
    return cols_matched


col1, col2, col3 = st.columns(3)

if "cols" not in st.session_state:
    st.session_state["cols"] = get_cols(True)
cols = st.session_state["cols"]

if "activities" not in st.session_state:
    st.session_state["activities"] = activities = get_activities()
activities = st.session_state["activities"]

with col1:
    st.metric(label="Activités strava", value=activities.shape[0])

if "cols_matched" not in st.session_state:
    st.session_state["cols_matched"] = match_cols(cols, activities)

cols_matched = st.session_state["cols_matched"]

with col2:
    st.metric(label="Cols passés", value=cols_matched.col_id.nunique())

st.markdown("# Nombre de cols passés par an")

st.bar_chart(data=cols_matched.reset_index().groupby("start_year").agg({"activity_id": "size"}).reset_index().rename(columns={"start_year": "Année", "activity_id": "Cols"}), x="Année", y="Cols", height=250)

displayed_cols = cols_matched.reset_index() \
    .groupby("col_id") \
    .agg({"nom": "size", "activity_id": list, "start_date": "min"}) \
    .rename(columns={"nom": "Passages", "start_date": "1ère fois"}) \
    .merge(cols[["nom", "altitude", "departement", "liencols"]].reset_index(), on="col_id") \
    .rename(columns={"nom": "Col", "altitude": "Alt.", "departement": "Dpt.", "liencols": "Lien"}) \
    [["Col", "Dpt.", "Alt.", "Passages", "1ère fois", "Lien"]]

st.markdown("# Liste des cols passés")
st.dataframe(displayed_cols, hide_index=True, column_config={
    "Lien": st.column_config.LinkColumn(),
    "1ère fois": st.column_config.DateColumn(),
})

with col3:
    if displayed_cols.shape[0] > 0:
        st.metric(label="Le plus haut", value=f"{int(displayed_cols['Alt.'].fillna(0).max())}m")

st.markdown("""
# Carte des cols
*Cliquez sur un parcours pour aller le voir sur Strava*
""")
            
cols_with_indicator = cols.reset_index().merge(cols_matched.reset_index()[["col_id"]].drop_duplicates(), on="col_id", indicator=True, how="left")

bounds = activities.total_bounds
m = folium.Map()
m.fit_bounds([[bounds[3], bounds[0]],[bounds[1], bounds[2]]])

icon_ok = lambda: folium.features.DivIcon(html='<div style="height: 100%; width: 100%; background: limegreen; border: 2px solid #fff;" />')
icon_ko = lambda: folium.features.DivIcon(html='<div style="height: 100%; width: 100%; background: orange; border: 2px solid #fff" />')

fg = folium.FeatureGroup()
for id, a in activities.iterrows():
    if a.polyline:
        fg.add_child(folium.PolyLine(a.polyline, popup=f"[{a.start_date}] <a href='https://www.strava.com/activities/{id}' target='_blank'>{a.name}</a>"))
    
for id, a in cols_with_indicator[cols_with_indicator._merge=="left_only"].iterrows():
    if a.latlng:
         fg.add_child(folium.Marker(location=a.latlng, tooltip=a.nom, icon=icon_ko()))

for id, a in cols_with_indicator[cols_with_indicator._merge=="both"].iterrows():
    if a.latlng:
         fg.add_child(folium.Marker(location=a.latlng, tooltip=a.nom, icon=icon_ok()))

st_data = streamlit_folium.st_folium(m, feature_group_to_add=fg, use_container_width=True, returned_objects=[])
