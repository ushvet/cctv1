"""
Hikvision AI CCTV Platform — ISAPI XML Parser Unit Tests
Tests parsing of Hikvision ISAPI alertStream XML event payloads.
"""

import pytest
from app.services.isapi_listener import parse_isapi_xml, ISAPIEvent


# -------------------------------------------------------
# Sample XML Payloads (real Hikvision format)
# -------------------------------------------------------
LINE_CROSSING_XML = """
<EventNotificationAlert version="2.0"
    xmlns="http://www.hikvision.com/ver20/XMLSchema">
    <ipAddress>192.168.1.100</ipAddress>
    <portNo>80</portNo>
    <protocol>HTTP</protocol>
    <macAddress>aa:bb:cc:dd:ee:ff</macAddress>
    <channelID>1</channelID>
    <dateTime>2026-10-26T23:15:30+05:30</dateTime>
    <activePostCount>1</activePostCount>
    <eventType>linedetection</eventType>
    <eventState>active</eventState>
    <eventDescription>linedetection alarm</eventDescription>
    <DetectionRegionList>
        <DetectionRegionEntry>
            <regionID>1</regionID>
            <sensitivityLevel>60</sensitivityLevel>
            <targetAttrs>
                <human/>
            </targetAttrs>
        </DetectionRegionEntry>
    </DetectionRegionList>
</EventNotificationAlert>
"""

INTRUSION_VEHICLE_XML = """
<EventNotificationAlert version="2.0"
    xmlns="http://www.hikvision.com/ver20/XMLSchema">
    <ipAddress>192.168.1.100</ipAddress>
    <channelID>3</channelID>
    <dateTime>2026-10-26T22:00:00+05:30</dateTime>
    <eventType>fielddetection</eventType>
    <eventState>active</eventState>
    <DetectionRegionList>
        <DetectionRegionEntry>
            <regionID>1</regionID>
            <targetAttrs>
                <vehicle/>
            </targetAttrs>
        </DetectionRegionEntry>
    </DetectionRegionList>
</EventNotificationAlert>
"""

MOTION_XML = """
<EventNotificationAlert version="2.0"
    xmlns="http://www.hikvision.com/ver20/XMLSchema">
    <channelID>2</channelID>
    <dateTime>2026-10-26T18:30:00+05:30</dateTime>
    <eventType>VMD</eventType>
    <eventState>active</eventState>
</EventNotificationAlert>
"""

INACTIVE_EVENT_XML = """
<EventNotificationAlert version="2.0"
    xmlns="http://www.hikvision.com/ver20/XMLSchema">
    <channelID>1</channelID>
    <dateTime>2026-10-26T23:20:00+05:30</dateTime>
    <eventType>linedetection</eventType>
    <eventState>inactive</eventState>
</EventNotificationAlert>
"""

FACE_DETECTION_XML = """
<EventNotificationAlert version="2.0"
    xmlns="http://www.hikvision.com/ver20/XMLSchema">
    <channelID>1</channelID>
    <dateTime>2026-10-26T23:25:00+05:30</dateTime>
    <eventType>facedetection</eventType>
    <eventState>active</eventState>
    <DetectionRegionList>
        <DetectionRegionEntry>
            <targetAttrs>
                <human/>
            </targetAttrs>
            <confidence>85</confidence>
        </DetectionRegionEntry>
    </DetectionRegionList>
</EventNotificationAlert>
"""

MALFORMED_XML = "<not-valid-xml"

EMPTY_XML = """
<EventNotificationAlert version="2.0"
    xmlns="http://www.hikvision.com/ver20/XMLSchema">
</EventNotificationAlert>
"""


# -------------------------------------------------------
# Tests
# -------------------------------------------------------
class TestISAPIParser:
    """Test suite for Hikvision ISAPI XML event parsing."""

    def test_parse_line_crossing_human(self):
        """Parse a line crossing event with human target classification."""
        event = parse_isapi_xml(LINE_CROSSING_XML, recorder_ip="192.168.1.100")

        assert event is not None
        assert event.event_type == "linedetection"
        assert event.channel_id == 1
        assert event.target_type == "human"
        assert event.is_active is True
        assert event.recorder_ip == "192.168.1.100"
        assert event.event_source == "isapi_linedetection"

    def test_parse_intrusion_vehicle(self):
        """Parse an intrusion (field detection) event with vehicle target."""
        event = parse_isapi_xml(INTRUSION_VEHICLE_XML, recorder_ip="192.168.1.100")

        assert event is not None
        assert event.event_type == "fielddetection"
        assert event.channel_id == 3
        assert event.target_type == "vehicle"
        assert event.is_active is True

    def test_parse_motion_detection(self):
        """Parse a basic motion detection event without AcuSense targets."""
        event = parse_isapi_xml(MOTION_XML)

        assert event is not None
        assert event.event_type == "VMD"
        assert event.channel_id == 2
        assert event.target_type == "unknown"
        assert event.is_active is True

    def test_parse_inactive_event(self):
        """Verify that inactive events are correctly flagged."""
        event = parse_isapi_xml(INACTIVE_EVENT_XML)

        assert event is not None
        assert event.is_active is False
        assert event.event_type == "linedetection"

    def test_parse_face_detection_with_confidence(self):
        """Parse a face detection event with confidence score."""
        event = parse_isapi_xml(FACE_DETECTION_XML)

        assert event is not None
        assert event.event_type == "facedetection"
        assert event.target_type == "human"
        assert event.confidence == 0.85  # 85/100

    def test_parse_malformed_xml(self):
        """Ensure malformed XML returns None gracefully."""
        event = parse_isapi_xml(MALFORMED_XML)
        assert event is None

    def test_parse_empty_event(self):
        """Ensure empty EventNotificationAlert returns None (no eventType)."""
        event = parse_isapi_xml(EMPTY_XML)
        assert event is None

    def test_timestamp_parsing(self):
        """Verify ISO 8601 timestamp parsing from Hikvision format."""
        event = parse_isapi_xml(LINE_CROSSING_XML)

        assert event is not None
        assert event.timestamp.year == 2026
        assert event.timestamp.month == 10
        assert event.timestamp.day == 26

    def test_recorder_ip_passthrough(self):
        """Verify recorder IP is correctly attached to parsed events."""
        event = parse_isapi_xml(MOTION_XML, recorder_ip="192.168.1.101")
        assert event is not None
        assert event.recorder_ip == "192.168.1.101"

    def test_event_source_format(self):
        """Verify event_source property produces correct format."""
        event = parse_isapi_xml(INTRUSION_VEHICLE_XML)
        assert event.event_source == "isapi_fielddetection"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
