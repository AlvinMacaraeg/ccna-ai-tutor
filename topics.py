"""CCNA topic list, grouped roughly by exam blueprint area."""

TOPICS = [
    # Network Fundamentals
    "OSI Model",
    "TCP/IP Model",
    "IPv4 Addressing & Subnetting",
    "IPv6 Addressing",
    "Ethernet & Switching Basics",
    "Troubleshooting Methodology",
    # Network Access
    "VLANs",
    "Trunking (802.1Q)",
    "Spanning Tree Protocol (STP)",
    "EtherChannel",
    "Wireless Fundamentals",
    # IP Connectivity
    "Static Routing",
    "OSPF",
    "EIGRP Basics",
    "Administrative Distance & Route Selection",
    "First Hop Redundancy (HSRP/VRRP)",
    # IP Services
    "NAT",
    "DHCP",
    "DNS",
    "NTP",
    "QoS Basics",
    # Security Fundamentals
    "ACLs",
    "Port Security",
    "VPN Fundamentals",
    "AAA & Device Hardening",
    # Automation & Programmability
    "Network Automation Basics",
    "REST APIs & JSON",
]

# Real CCNA 200-301 blueprint domain weights, used to proportion the mock exam
# so it mirrors the actual test rather than sampling topics evenly.
DOMAINS = {
    "Network Fundamentals": {
        "weight": 0.20,
        "topics": ["OSI Model", "TCP/IP Model", "IPv4 Addressing & Subnetting",
                   "IPv6 Addressing", "Ethernet & Switching Basics", "Troubleshooting Methodology"],
    },
    "Network Access": {
        "weight": 0.20,
        "topics": ["VLANs", "Trunking (802.1Q)", "Spanning Tree Protocol (STP)",
                   "EtherChannel", "Wireless Fundamentals"],
    },
    "IP Connectivity": {
        "weight": 0.25,
        "topics": ["Static Routing", "OSPF", "EIGRP Basics",
                   "Administrative Distance & Route Selection", "First Hop Redundancy (HSRP/VRRP)"],
    },
    "IP Services": {
        "weight": 0.10,
        "topics": ["NAT", "DHCP", "DNS", "NTP", "QoS Basics"],
    },
    "Security Fundamentals": {
        "weight": 0.15,
        "topics": ["ACLs", "Port Security", "VPN Fundamentals", "AAA & Device Hardening"],
    },
    "Automation & Programmability": {
        "weight": 0.10,
        "topics": ["Network Automation Basics", "REST APIs & JSON"],
    },
}

# Topics that map to real Cisco IOS configuration commands — used by CLI practice mode.
# (Concepts like "OSI Model" or "DNS" don't have a config-mode command sequence to drill.)
CLI_PRACTICE_TOPICS = [
    "VLANs",
    "Trunking (802.1Q)",
    "EtherChannel",
    "Static Routing",
    "OSPF",
    "EIGRP Basics",
    "First Hop Redundancy (HSRP/VRRP)",
    "NAT",
    "DHCP",
    "ACLs",
    "Port Security",
    "AAA & Device Hardening",
]


def default_topic_row(topic: str) -> dict:
    """Initial spaced-repetition state for a topic that's never been quizzed."""
    return {
        "topic": topic,
        "ease": 2.5,         # SM-2 ease factor
        "interval_days": 0,  # days until next due
        "reps": 0,           # successful reps in a row
        "last_seen": None,   # ISO date string
        "next_due": None,    # ISO date string, None = due now (never studied)
        "attempts": 0,
        "correct": 0,
    }


# Classic CCNA concept pairs students commonly confuse — used by comparison drills.
COMPARISON_PAIRS = [
    ("OSPF", "EIGRP"),
    ("TCP", "UDP"),
    ("Standard ACLs", "Extended ACLs"),
    ("Static Routing", "Dynamic Routing (OSPF/EIGRP)"),
    ("Trunk Ports", "Access Ports"),
    ("IPv4 Addressing", "IPv6 Addressing"),
    ("Switches (Layer 2 Forwarding)", "Routers (Layer 3 Forwarding)"),
    ("HSRP", "VRRP"),
    ("NAT", "PAT"),
    ("Public IP Addresses", "Private IP Addresses"),
]
