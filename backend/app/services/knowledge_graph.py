"""
Build a NetworkX knowledge graph from the fixed curriculum JSON.
Nodes: subject / unit / topic
Edges: part_of , prerequisite_of
"""
from typing import Dict, Any, List
import networkx as nx
from networkx.readwrite import json_graph

def build_knowledge_graph(curriculum: Dict[str, Any]) -> nx.DiGraph:
    """
    curriculum must be the full object:
    {
      "curriculum": {
        "version": "1.0",
        "subjects": [...]
      }
    }
    or just the inner "curriculum" dict. Both are accepted.
    """
    if "curriculum" in curriculum:
        data = curriculum["curriculum"]
    else:
        data = curriculum

    G = nx.DiGraph()

    for subject in data.get("subjects", []):
        subject_id = subject["subject_id"]
        subject_title = subject.get("subject_title", subject_id)

        # Subject node
        G.add_node(
            subject_id,
            type="subject",
            title=subject_title,
            description=subject.get("description", ""),
            node_key=subject_id,
        )

        prev_unit_key = None
        prev_topic_key = None  # carries across units so the whole subject's
                                # topics form one continuous prerequisite
                                # chain, not one chain per unit. Without this,
                                # topological_sort has no ordering constraint
                                # between, say, the last topic of Unit 1 and
                                # the first topic of Unit 2 (only the *unit*
                                # nodes were chained), so topics from a later
                                # unit could sort ahead of earlier-unit topics.

        for unit in subject.get("units", []):
            unit_number = unit["unit_number"]
            unit_title = unit.get("unit_title", f"Unit {unit_number}")
            unit_key = f"{subject_id}-U{unit_number}"

            # Unit node
            G.add_node(
                unit_key,
                type="unit",
                title=unit_title,
                unit_number=unit_number,
                subject_id=subject_id,
                node_key=unit_key,
            )

            # part_of: unit → subject
            G.add_edge(unit_key, subject_id, relation="part_of")

            # Sequential prerequisite between units (MVP rule)
            if prev_unit_key is not None:
                G.add_edge(prev_unit_key, unit_key, relation="prerequisite_of")
            prev_unit_key = unit_key

            for topic in unit.get("topics", []):
                topic_id = topic["topic_id"]
                topic_title = topic.get("title", topic_id)
                duration = topic.get("duration_minutes", 45)

                # Topic node
                G.add_node(
                    topic_id,
                    type="topic",
                    title=topic_title,
                    duration_minutes=duration,
                    unit_key=unit_key,
                    subject_id=subject_id,
                    node_key=topic_id,
                )

                # part_of: topic → unit
                G.add_edge(topic_id, unit_key, relation="part_of")

                # Sequential prerequisite across the *whole subject's* topics,
                # not just within one unit (see prev_topic_key comment above).
                if prev_topic_key is not None:
                    G.add_edge(prev_topic_key, topic_id, relation="prerequisite_of")
                prev_topic_key = topic_id

    return G

def graph_to_dict(G: nx.DiGraph) -> Dict[str, Any]:
    """Serialize for storage / API response."""
    return json_graph.node_link_data(G)

def dict_to_graph(data: Dict[str, Any]) -> nx.DiGraph:
    return json_graph.node_link_graph(data)

def get_prerequisites(G: nx.DiGraph, node_key: str) -> List[str]:
    """Return direct prerequisite nodes (incoming prerequisite_of edges)."""
    preds = []
    for pred in G.predecessors(node_key):
        edge_data = G.get_edge_data(pred, node_key)
        if edge_data and edge_data.get("relation") == "prerequisite_of":
            preds.append(pred)
    return preds

# NOTE FOR FUTURE:
# Real prerequisite extraction from syllabus text can be added here.
# e.g. look for phrases "requires knowledge of", "builds upon", "after completing"
# and create extra prerequisite_of edges between topics/units.












def generate_roadmap(G: nx.DiGraph, subject_id: str) -> List[Dict[str, Any]]:
    """
    Return a linear learning order for the given subject_id by
    topological sort over the subgraph of that subject.
    Only nodes that belong to the subject are considered.
    """
    # Collect all nodes belonging to this subject
    subject_nodes = [
        n for n, d in G.nodes(data=True)
        if d.get("subject_id") == subject_id or n == subject_id
    ]

    if not subject_nodes:
        return []

    subG = G.subgraph(subject_nodes).copy()

    try:
        order = list(nx.topological_sort(subG))
    except nx.NetworkXUnfeasible:
        # Cycle detected – fall back to a simple unit-then-topic order
        order = sorted(
            subject_nodes,
            key=lambda n: (
                0 if G.nodes[n].get("type") == "subject" else
                1 if G.nodes[n].get("type") == "unit" else 2,
                G.nodes[n].get("unit_number", 0),
                n,
            ),
        )

    roadmap = []
    for node in order:
        data = G.nodes[node]
        if data.get("type") == "subject":
            continue  # skip the subject node itself in the learning sequence
        roadmap.append({
            "node_key": node,
            "type": data.get("type"),
            "title": data.get("title"),
            "unit_number": data.get("unit_number"),
            "duration_minutes": data.get("duration_minutes"),
            "subject_id": data.get("subject_id", subject_id),
        })
    return roadmap