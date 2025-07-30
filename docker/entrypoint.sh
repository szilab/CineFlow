#!/bin/sh

# Copy example files to the config directory empty
if [ -z "$(ls -A $CFG_DIRECTORY)" ]; then
    echo "Config directory is empty, copying example files..."
    cp -r $EXAMPLES_DIRECTORY/* $CFG_DIRECTORY/
fi

cineflow "$@"