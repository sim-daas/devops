import pulumi
import pulumi_aws as aws

# --- Configuration ---
# Use the t3.small instance type as requested for at least 1.5 GiB RAM
INSTANCE_TYPE = "t3.small"
# Name prefix for all resources
NAME_PREFIX = "selenium-server"

# --- 1. Network Foundation (VPC and Subnets) ---
# Create a new VPC for isolated deployment
vpc = aws.ec2.Vpc(f"{NAME_PREFIX}-vpc",
    cidr_block="10.0.0.0/16",
    enable_dns_support=True,
    enable_dns_hostnames=True,
    tags={"Name": f"{NAME_PREFIX}-vpc"}
)

# Create a public subnet in the first available AZ
subnet = aws.ec2.Subnet(f"{NAME_PREFIX}-subnet",
    vpc_id=vpc.id,
    cidr_block="10.0.1.0/24",
    # Automatically assign a public IP to instances launched in this subnet
    map_public_ip_on_launch=True,
    tags={"Name": f"{NAME_PREFIX}-public-subnet"}
)

# Create an Internet Gateway and attach it to the VPC
igw = aws.ec2.InternetGateway(f"{NAME_PREFIX}-igw",
    vpc_id=vpc.id,
    tags={"Name": f"{NAME_PREFIX}-igw"}
)

# Create a Route Table and route all traffic (0.0.0.0/0) to the Internet Gateway
route_table = aws.ec2.RouteTable(f"{NAME_PREFIX}-rt",
    vpc_id=vpc.id,
    routes=[
        aws.ec2.RouteTableRouteArgs(
            cidr_block="0.0.0.0/0",
            gateway_id=igw.id,
        )
    ],
    tags={"Name": f"{NAME_PREFIX}-rt"}
)

# Associate the Route Table with the Subnet
aws.ec2.RouteTableAssociation(f"{NAME_PREFIX}-rta",
    subnet_id=subnet.id,
    route_table_id=route_table.id
)

# --- 2. Security Group (Firewall) ---
sec_group = aws.ec2.SecurityGroup(f"{NAME_PREFIX}-sg",
    vpc_id=vpc.id,
    description="Allow SSH (22) and HTTP (80) inbound access",
    ingress=[
        # Allow SSH from anywhere (0.0.0.0/0), but in production, restrict this to your IP range!
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=22,
            to_port=22,
            cidr_blocks=["0.0.0.0/0"],
        ),
        # Allow HTTP for the web server
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=6080,
            to_port=6080,
            cidr_blocks=["0.0.0.0/0"],
        )
    ],
    # Allow all outbound traffic
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"],
        )
    ]
)

# --- 3. EC2 Configuration and Launch ---

# Find the latest official Debian 12 AMI
ami = aws.ec2.get_ami(
    most_recent=True,
    owners=["136693071363"],  # Official Debian owner ID for AWS Marketplace
    filters=[
        aws.ec2.GetAmiFilterArgs(
            name="name",
            values=["debian-12-amd64-*"],
        ),
        aws.ec2.GetAmiFilterArgs(
            name="architecture",
            values=["x86_64"],
        ),
        aws.ec2.GetAmiFilterArgs(
            name="root-device-type",
            values=["ebs"],
        ),
        aws.ec2.GetAmiFilterArgs(
            name="virtualization-type",
            values=["hvm"],
        ),
    ]
)

# User data script to set up the environment
user_data_script = '''#!/bin/bash
# Redirect all output to log file for debugging
exec > /var/log/user-data.log 2>&1
set -eux
export DEBIAN_FRONTEND=noninteractive

echo "Starting user data script execution..."

apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-setuptools \
    firefox-esr \
    xfce4 xfce4-goodies xfce4-session \
    x11vnc xvfb \
    wget ca-certificates \
    supervisor \
    dbus-x11 \
    fonts-dejavu \
    novnc websockify \
    git

apt-get remove -y python3-urllib3 || true
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "Installing Python packages..."
pip3 install --no-cache-dir --break-system-packages --ignore-installed selenium requests beautifulsoup4 websockify fastapi uvicorn

echo "Setting up VNC password for admin user..."
su - admin -c "mkdir -p /home/admin/.vnc"
su - admin -c 'echo "312" | x11vnc -storepasswd - /home/admin/.vnc/passwd'
chown -R admin:admin /home/admin/.vnc

echo "Installing noVNC..."
mkdir -p /opt/novnc
wget -qO- https://github.com/novnc/noVNC/archive/refs/tags/v1.4.0.tar.gz | tar xz --strip-components=1 -C /opt/novnc
ln -sf /opt/novnc/vnc.html /opt/novnc/index.html

echo "Cloning GitHub repository..."
su - admin -c "git clone https://github.com/sim-daas/agents /home/admin/agents" || true

echo "User data script completed successfully!"
'''

# Launch the EC2 Instance
instance = aws.ec2.Instance(f"{NAME_PREFIX}-instance",
    instance_type=INSTANCE_TYPE,
    ami=ami.id,
    subnet_id=subnet.id,
    vpc_security_group_ids=[sec_group.id],
    key_name="ishaan_selenium",  # Use your existing AWS key pair name
    user_data=user_data_script,
    tags={"Name": f"{NAME_PREFIX}-instance"}
)

# --- 4. Outputs ---
# Export the public IP and the URL to check the deployed web server
pulumi.export("instance_public_ip", instance.public_ip)