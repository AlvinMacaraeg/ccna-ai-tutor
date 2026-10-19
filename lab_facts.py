"""
Hand-curated platform facts + universal lab-design rules.

These get injected into EVERY lab-style generator and grader (CLI practice, Packet Tracer
labs, troubleshooting cases, real-world scenarios). Language models get device-specific
details wrong when they rely on memory (e.g. which switch models support which commands);
plain facts placed in the prompt are far more reliable than recall.

THIS FILE IS HAND-WRITTEN. If Packet Tracer ever disagrees with a line here, the simulator
wins -- fix the line. Mistakes you flag inside the app (Progress & History > Reported lab
mistakes) are good candidates to promote into this file permanently.
"""

# ---------------------------------------------------------------------------
# Facts that apply to every lab, regardless of topic
# ---------------------------------------------------------------------------
PLATFORM_FACTS = """\
DEVICE MODELS (Cisco Packet Tracer, CCNA level)
- Catalyst 2960 (Packet Tracer 2960-24TT) is a LAYER 2 switch: 24 FastEthernet ports
  (Fa0/1-24) plus 2 GigabitEthernet uplinks (Gi0/1-2).
  * It CANNOT route and has no `ip routing`.
  * It supports 802.1Q only, so `switchport trunk encapsulation dot1q` does NOT exist on it
    (rejected as invalid input). Use `switchport mode trunk` by itself.
  * An SVI (`interface vlan N`) on it is only a MANAGEMENT address, never a gateway for hosts.
    To reach other subnets it uses `ip default-gateway <router or L3-switch IP>`.
- Catalyst 3560 (Packet Tracer 3560-24PS) is a LAYER 3-capable switch (24 FastEthernet + 2
  GigabitEthernet). It supports both ISL and 802.1Q, so `switchport trunk encapsulation dot1q`
  must be entered BEFORE `switchport mode trunk` (otherwise the trunk command is rejected).
  Inter-VLAN routing needs `ip routing` in global config plus one SVI with an IP per VLAN;
  those SVIs are the hosts' default gateways.
- Routers (e.g. 1941, 2911, ISR4331): every interface is administratively down until
  `no shutdown`. Interface names differ by model (e.g. GigabitEthernet0/0 and 0/1 on a 1941;
  the ISR4331 uses three-part names such as GigabitEthernet0/0/0). Use only names that exist
  on the model you chose, and say which model it is.
- Router-on-a-stick: the physical router interface gets `no shutdown` and NO IP address; each
  VLAN gets a subinterface (`interface Gi0/0.10`, `encapsulation dot1q 10`, `ip address ...`).
  The switch port facing the router must be a TRUNK.
- End hosts (Packet Tracer PC): the IP is set under Desktop > IP Configuration. The PC command
  prompt supports ping, ipconfig, tracert, arp and nslookup, but not `show` commands.

SWITCHING DEFAULTS
- Switch ports are up by default and belong to VLAN 1.
- VLANs 2-1001 live in each switch's OWN local VLAN database: create a VLAN explicitly on every
  switch that uses it (VTP is not configured unless a lab says so).
- Default DTP mode on 2960/3560 is dynamic auto: two dynamic-auto ports do NOT form a trunk.
  Set at least one side to `trunk` or `dynamic desirable` explicitly.
- Native VLAN is 1 by default and must match on both ends of a trunk.

VERIFICATION COMMANDS
- show ip interface brief | show vlan brief | show interfaces trunk | show running-config
- show ip route | show ip protocols | show mac address-table | show spanning-tree
- show etherchannel summary | show port-security interface <int> | show access-lists
- show ip nat translations | show ip ospf neighbor | show standby brief
"""

# ---------------------------------------------------------------------------
# Facts that only matter for a particular topic (keys match topics.py names)
# ---------------------------------------------------------------------------
TOPIC_FACTS = {
    "VLANs": """\
- Create with `vlan <id>` then `name <name>`. Assign a host port with `switchport mode access`
  and `switchport access vlan <id>`. Verify with `show vlan brief`.
- Hosts in different VLANs cannot talk without a Layer 3 device (router subinterfaces or an L3
  switch with `ip routing`).""",

    "Trunking (802.1Q)": """\
- 2960: `switchport mode trunk` only. 3560: `switchport trunk encapsulation dot1q` first, then
  `switchport mode trunk`.
- Restrict VLANs with `switchport trunk allowed vlan <list>`; change the native VLAN with
  `switchport trunk native vlan <id>` (must match on both ends).
- Verify with `show interfaces trunk`.""",

    "EtherChannel": """\
- Under `interface range`: `channel-group <n> mode active|passive` (LACP) or `desirable|auto`
  (PAgP) or `on` (static). Never mix LACP and PAgP. Compatible pairs: active-active,
  active-passive, desirable-desirable, desirable-auto, on-on.
- Member ports must match in speed, duplex, VLAN and trunk settings. The logical interface is
  `interface port-channel <n>`. Verify with `show etherchannel summary`.""",

    "Static Routing": """\
- `ip route <network> <mask> <next-hop | exit-interface>`; default route is
  `ip route 0.0.0.0 0.0.0.0 <next-hop>`. Administrative distance 1.
- A static route only works if the next hop is reachable and the exit interface is up.""",

    "OSPF": """\
- `router ospf <process-id>` (process ID is only locally significant), then
  `network <address> <wildcard-mask> area <n>`.
- Neighbors must match on area, subnet, hello/dead timers and authentication.
  Defaults: hello 10 / dead 40 on broadcast and point-to-point links.
- DR/BDR election (broadcast networks only): highest priority, then highest router ID.
  Administrative distance 110. Verify with `show ip ospf neighbor`.""",

    "EIGRP Basics": """\
- `router eigrp <AS>` then `network <address> [wildcard]`. The AS number must match on
  neighbors. Administrative distance 90 (internal).""",

    "Administrative Distance & Route Selection": """\
- Administrative distance: connected 0, static 1, EIGRP 90, OSPF 110, RIP 120.
- The longest matching prefix wins first; administrative distance only breaks ties between
  different sources for the SAME prefix; metric breaks ties within one protocol.""",

    "First Hop Redundancy (HSRP/VRRP)": """\
- HSRP: `standby <group> ip <virtual-ip>`, `standby <group> priority <n>` (default 100),
  `standby <group> preempt`. Hosts use the virtual IP as their gateway.
- Needs Layer 3 interfaces (routers or an L3 switch) -- NOT a 2960. Verify with
  `show standby brief`.""",

    "NAT": """\
- Mark interfaces with `ip nat inside` / `ip nat outside`.
- PAT: `ip nat inside source list <ACL> interface <int> overload`.
- Static NAT: `ip nat inside source static <inside-local> <inside-global>`.
- Verify with `show ip nat translations`.""",

    "DHCP": """\
- Router pool: `ip dhcp pool <name>`, `network <addr> <mask>`, `default-router <ip>`,
  `dns-server <ip>`. Exclude addresses with `ip dhcp excluded-address` in GLOBAL config.
- If the DHCP server is on another subnet, the client-facing router interface needs
  `ip helper-address <server-ip>`.""",

    "ACLs": """\
- Standard ACLs (1-99, 1300-1999) match source only: place them close to the DESTINATION.
  Extended ACLs (100-199, 2000-2699) match source, destination, protocol and port: place them
  close to the SOURCE.
- Every ACL ends with an implicit `deny any`. Apply with `ip access-group <n|name> in|out` under
  the interface. Named: `ip access-list standard|extended <name>`.
- Verify with `show access-lists`.""",

    "Port Security": """\
- The port must be a static access port first (`switchport mode access`), then
  `switchport port-security`, optionally `switchport port-security maximum <n>` and
  `switchport port-security mac-address sticky`.
- Violation modes: protect, restrict, shutdown (default). A shutdown violation puts the port
  in err-disabled; recover with `shutdown` then `no shutdown`.""",

    "AAA & Device Hardening": """\
- Prefer `enable secret` over `enable password`. `service password-encryption` only applies weak
  type-7 obfuscation.
- SSH needs: a non-default hostname, `ip domain-name`, `crypto key generate rsa`, a local user
  (`username <u> secret <p>`), and on the lines `login local` + `transport input ssh`.""",

    "Spanning Tree Protocol (STP)": """\
- Root bridge = lowest Bridge ID (priority, then MAC). Default priority 32768 plus the VLAN ID.
  Priorities are multiples of 4096. `spanning-tree vlan <n> root primary` sets it for you.
- PortFast and BPDU Guard belong only on access ports facing end hosts.""",

    "IPv4 Addressing & Subnetting": """\
- The network address and the broadcast address of a subnet cannot be assigned to hosts.
- Hosts and their default gateway must be inside the same subnet.""",
}

# ---------------------------------------------------------------------------
# Rules that apply to ALL lab-style generation (CLI, Packet Tracer, troubleshooting, scenarios)
# ---------------------------------------------------------------------------
LAB_DESIGN_RULES = """\
1. Name the exact device model for every router/switch and use ONLY commands, features and
   interface names that model supports (see the platform facts). If you are not sure a command
   exists on that model, avoid it.
2. Layer 2 switches never act as a host's default gateway. Routing between VLANs/subnets happens
   only on a router (subinterfaces or separate interfaces) or on a Layer 3 switch with
   `ip routing`.
3. Every VLAN a switch uses must be created explicitly on THAT switch. Do not rely on VTP
   unless the task is about VTP.
4. Respect command ordering and prerequisites (router interfaces need `no shutdown`; on a 3560
   set trunk encapsulation before trunk mode; port security needs `switchport mode access`
   first; build an ACL before applying it).
5. Make every verification step FALSIFIABLE: a check that would still pass when the configured
   feature is broken proves nothing. Examples: a trunk is verified by two hosts in the SAME VLAN
   on DIFFERENT switches pinging each other; routing by a ping that can only succeed if the new
   route exists; an ACL by one test that must be permitted and one that must be denied; NAT by
   `show ip nat translations`. State the expected result of every check.
6. Keep the addressing plan clean: one subnet per VLAN, masks stated, host and gateway addresses
   valid inside their subnet (never the network or broadcast address), no overlapping subnets,
   no duplicate IPs.
7. Everything you show must agree with itself: diagram, device list, IP table, instructions and
   expected results must match. Before writing, silently re-check every command, interface name
   and IP address against these rules.
8. For troubleshooting material: exactly ONE root cause, and every piece of command output shown
   must be consistent with that cause (no contradictions between outputs, no unrelated extra
   faults).
9. For topology / packet-flow questions: the correct answer must follow from the diagram exactly
   as drawn. Work it out hop by hop before writing the question.
10. Do not invent features, defaults or outputs. A simpler task that is 100% correct beats an
    ambitious one that might not be.
"""

# ---------------------------------------------------------------------------
# Extra guidance for graders (CLI, troubleshooting, scenario graders)
# ---------------------------------------------------------------------------
GRADER_RULES = """\
- Judge against the platform facts above, not against the task's wording: if the task text
  itself used a command or claim that is wrong for the stated device model, say so plainly and
  grade the student on what would actually work on that device.
- Accept any valid alternative solution (different but working commands, valid abbreviations,
  a different but correct ordering). Do not demand the exact wording from the task.
- If you are not certain the student's answer is wrong, say what to verify in the simulator
  instead of marking it wrong with false confidence.
"""


def _pitfalls_block(pitfalls) -> str:
    if not pitfalls:
        return ""
    lines = "\n".join(f"- {p}" for p in pitfalls)
    return (
        "=== KNOWN PITFALLS (mistakes the student already caught in earlier generated "
        "material -- do NOT repeat them) ===\n" + lines
    )


def _facts_for(topic) -> list:
    parts = ["=== PLATFORM FACTS (authoritative -- follow exactly) ===", PLATFORM_FACTS]
    topic_facts = TOPIC_FACTS.get(topic)
    if topic_facts:
        parts += [f"=== FACTS FOR THIS TOPIC: {topic} ===", topic_facts]
    return parts


def build_lab_context(topic, pitfalls=None) -> str:
    """Context appended to the system prompt of every lab-style GENERATOR."""
    parts = _facts_for(topic)
    parts += ["=== LAB DESIGN RULES (apply to everything you write) ===", LAB_DESIGN_RULES]
    block = _pitfalls_block(pitfalls)
    if block:
        parts.append(block)
    return "\n\n".join(parts)


def build_grader_context(topic, pitfalls=None) -> str:
    """Context appended to the system prompt of every lab-style GRADER."""
    parts = _facts_for(topic)
    parts += ["=== GRADING GUIDANCE ===", GRADER_RULES]
    block = _pitfalls_block(pitfalls)
    if block:
        parts.append(block)
    return "\n\n".join(parts)
