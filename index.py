import streamlit as st
import pandas as pd

# import requests
import polyline
import folium
import geopandas
import shapely

# from bs4 import BeautifulSoup
from stravalib.client import Client
import streamlit_folium

# strava = {
    # "redirect_uri": "http://localhost:8501/",
    # "client_id": 110595,
    # "client_secret": "69f13c7874897da2283b2d9b52288f095e0f1f9e",
# }

strava = st.secrets["strava"]

client = Client()

    # if "strava_access_token" not in st.session_state:

@st.cache_data(ttl=3600)
def get_strava_access_token():
    get_params = st.experimental_get_query_params()

    if not get_params.get("code"):
        authorized_url = client.authorization_url(client_id=strava["client_id"], redirect_uri=strava["redirect_uri"])
        st.markdown(f"<a href=\"{authorized_url}\" target=\"_blank\"><button>Se connecter à Strava</button></a>", unsafe_allow_html=True)
        st.stop()

    token = client.exchange_code_for_token(client_id=strava["client_id"], client_secret=strava["client_secret"], code=get_params["code"])
    st.experimental_set_query_params()
    return token

strava_token = get_strava_access_token()        
client.access_token = strava_token["access_token"]
client.refresh_token = strava_token["refresh_token"]
client.token_expires_at = strava_token["expires_at"]

@st.cache_data
def get_cols(cyclist_only=False):
    cols = pd.read_csv("cols.csv")
    cols = geopandas.GeoDataFrame(
        cols, 
        geometry=geopandas.points_from_xy(cols.lng, cols.lat)
    )

    if cyclist_only:
        cols = cols[cols.est_cycliste]

    return cols

@st.cache_data
def get_activities(limit=None, details=False):
    def get_polyline(id):
        activity = client.get_activity(id)
        return polyline.decode(activity.map.polyline)

    def get_linestring(polyline):
        if len(polyline)>=2:
            lnglat = [latlng[::-1] for latlng in polyline]
            return shapely.LineString(lnglat)
        return None

    iterator = client.get_activities(limit=limit)
    activities = []
    with st.empty():
        for activity in iterator:
            activities.append(activity)
            st.text=f"Nous chargeons vos activités... {len(activities)}"

    activities = pd.DataFrame([{
            "id": activity.id,
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

    activities["start_date"] = pd.to_datetime(activities["start_date"]).dt.date
    activities["start_year"] = pd.to_datetime(activities["start_date"]).dt.year

    if details:
        activities["polyline"] = activities.id.apply(get_polyline)

    activities = geopandas.GeoDataFrame(
        activities, 
        geometry=activities.polyline.apply(get_linestring)
    )

    activities.rename(columns={"id": "activity_id"}, inplace=True)
    activities.set_index("activity_id", inplace=True)

    return activities

def match_cols(cols, activities):
    placeholder = st.empty()
    progress_text = "Nous cherchons les cols..."
    with placeholder.container():
        progress_bar = st.progress(0, text=progress_text)

    dist_max = 0.001
    cols_matched = geopandas.GeoDataFrame()
    activities_buffer = activities.buffer(dist_max)

    i = 0
    for activity_id, geometry in activities_buffer.items():
        if geometry:
            df = cols[["nom", "geometry"]].copy()
            df["dist"] = cols.distance(geometry)
            df["activity_id"] = activity_id
            df = df[df.dist <= dist_max]
            cols_matched = pd.concat([cols_matched, df])
        i += 1
        progress_bar.progress(i / len(activities_buffer), text=progress_text)
    cols_matched["latlng"] = cols_matched.geometry.apply(lambda point: [point.xy[1][0], point.xy[0][0]])
    cols_matched = cols_matched.merge(activities.reset_index()[["activity_id", "start_date", "start_year"]], on="activity_id")
    placeholder.empty()
    return cols_matched

st.write("""
# Chasseur de cols

Grâce à vos données Strava, Chasseur de cols identifie tous les cols où vous êtes passé. 
""")

cols = get_cols(True)
activities = get_activities()
st.write(f"Nous avons trouvé {activities.shape[0]} activitiés")

if "cols_matched" not in st.session_state:
    st.session_state["cols_matched"] = match_cols(cols, activities)

cols_matched = st.session_state["cols_matched"]

st.write(f"Vous avez passé {len(cols_matched)} cols !")
st.bar_chart(data=cols_matched.groupby("start_year").size(), height=250)

displayed_cols = cols_matched.reset_index() \
    .groupby("index") \
    .agg({"nom": "size", "activity_id": list, "start_date": "min"}) \
    .rename(columns={"nom": "Passages", "start_date": "1ère fois"}) \
    .join(cols) \
    .rename(columns={"nom": "Col", "altitude": "Alt.", "departement": "Dpt.", "liencols": "Lien"}) \
    [["Col", "Dpt.", "Alt.", "Passages", "1ère fois", "Lien"]]

st.dataframe(displayed_cols, hide_index=True, column_config={
    "Lien": st.column_config.LinkColumn(),
    "1ère fois": st.column_config.DateColumn(),
})


bounds = activities.total_bounds

m = folium.Map()
m.fit_bounds([[bounds[3], bounds[0]],[bounds[1], bounds[2]]])

for id, a in activities.iterrows():
    if a.polyline:
        folium.PolyLine(a.polyline).add_to(m)
    
df = [[point.xy[1][0], point.xy[0][0]] for point in cols_matched.geometry]
for id, a in cols_matched.iterrows():
    if a.latlng:
         folium.Marker(location=a.latlng, tooltip=a.nom).add_to(m)

st_data = streamlit_folium.st_folium(m, width=700)
